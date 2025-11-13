#!/usr/bin/env python3
"""Heuristic converter from C++-style lines (from SPOC dataset) to Python lines.

Usage: python tools/cpp_to_py_converter.py <input_tsv> <output_tsv> [--examples N]

This script is intentionally conservative and heuristic-based. It handles common
patterns found in the dataset (declarations, cin/cout, for/while, basic funcs,
vectors/maps/sets, push_back/insert, etc.). It preserves indentation using the
`indent` column in the TSV and resets per-program state when `line` == 0.

Limitations: complex C++ idioms, macros, templates and low-level I/O won't be
perfectly translated. This is a first-pass automated conversion to speed up
manual review.
"""
import csv
import re
import sys
from pathlib import Path


def strip_type(s):
    # remove common C++ types and qualifiers from a parameter or declaration
    s = re.sub(r"\b(long long|long|int|short|bool|char|double|float|string)\b", "", s)
    s = re.sub(r"\b(const|std::|unsigned|signed|static|volatile)\b", "", s)
    s = re.sub(r"<[^>]+>", "", s)  # remove templates like vector<int>
    s = s.replace('*', '').replace('&', '')
    return s.strip()


def convert_decl(line, types):
    # e.g. 'int n, m, su = 0, su2 = 0, a, b, c;' -> create python assignments and record types
    m = re.match(r"^(?:[\w\s:<>,]+)\s+(.+);$", line)
    if not m:
        return None
    body = m.group(1)
    parts = [p.strip() for p in body.split(',')]
    out_lines = []
    for p in parts:
        if '=' in p:
            name, val = [x.strip() for x in p.split('=', 1)]
            # track type default to int
            types[name] = 'int'
            out_lines.append(f"{name} = {val}")
        else:
            name = p
            # remove array notation: s1[110] -> s1
            name = re.sub(r"\[.*\]", "", name).strip()
            if name:
                types[name] = 'int'
                out_lines.append(f"{name} = 0")
    return '\n'.join(out_lines)


def convert_cin(line, types):
    # convert cin >> a >> b; -> a, b = map(int, input().split()) or strings if declared
    line = line.strip().rstrip(';')
    if not line.startswith('cin >>'):
        return None
    rest = line[len('cin >>'):].strip()
    vars = [v.strip() for v in rest.split('>>')]
    # decide types
    if all(types.get(v) == 'string' for v in vars if v in types):
        return f"{', '.join(vars)} = input().split()"
    else:
        return f"{', '.join(vars)} = map(int, input().split())" if len(vars) > 1 else f"{vars[0]} = int(input())"


def convert_cout(line):
    # convert cout << a << "/" << b << "\n"; -> print(f"{a}/{b}") conservative
    s = line.strip().rstrip(';')
    if not s.startswith('cout <<'):
        return None
    parts = [p.strip() for p in s.split('<<')[1:]]
    items = []
    for p in parts:
        if p in ('endl', '"\\n"', '\"\\n\"'):
            continue
        # string literal
        if p.startswith('"') or p.startswith("'"):
            items.append(p.strip('"\''))
        else:
            items.append('{' + p + '}')
    # build f-string
    fstr = ''.join(items)
    # escape braces inside literals
    fstr = fstr.replace('{', '{{').replace('}', '}}') if not any(t.startswith('{') for t in items) else fstr
    # Better approach: rebuild with expressions in braces
    parts2 = []
    for p in parts:
        if p.startswith('"') or p.startswith("'"):
            parts2.append(p.strip('"\''))
        else:
            parts2.append(f"{{{p}}}")
    fstr = ''.join(parts2)
    return f"print(f\"{fstr}\")"


def convert_for(line):
    # handle common for loops
    m = re.match(r"for\s*\(\s*(?:int\s+)?(\w+)\s*=\s*(.+?)\s*;\s*\1\s*([<>=!]+)\s*(.+?)\s*;\s*(?:\+\+|\+\+\1|\1\+\+|\1\+\+)\s*\)", line)
    if m:
        var, start, op, end = m.groups()
        start = start.strip()
        end = end.strip()
        # handle <= and <
        if op == '<':
            return f"for {var} in range({start}, {end}):"
        if op == '<=':
            # try to simplify patterns like n - 1
            if re.match(r"(\w+)\s*-\s*1", end):
                en = re.sub(r"\s*-\s*1", "", end)
                return f"for {var} in range({start}, {en}):"
            return f"for {var} in range({start}, {end} + 1):"
        if op in ('>','>='):
            return f"# TODO: translate C++ for descending loop: {line}"
    # fallback: try to catch simple i=0;i<n;i++
    m2 = re.match(r"for\s*\(\s*(\w+)\s*=\s*(\d+)\s*;\s*\1\s*<\s*(\w+)\s*;\s*\1\+\+\s*\)", line)
    if m2:
        var, start, end = m2.groups()
        return f"for {var} in range({start}, {end}):"
    return None


def convert_while(line):
    # handle while(condition) { and inline statements separated by commas
    s = line.strip().rstrip(';')
    if not s.startswith('while'):
        return None
    m = re.match(r"while\s*\((.+)\)\s*(.*)", s)
    if not m:
        return None
    cond, rest = m.groups()
    cond = cond.strip()
    py = f"while {cond}:"
    # rest may contain comma-separated statements like 'ans += nn % i, nn /= i'
    rest = rest.strip()
    if rest:
        stmts = [st.strip() for st in rest.split(',')]
        return (py, stmts)
    return (py, None)


def convert_function_def(line):
    # e.g. int gcd(int a, int b) {
    m = re.match(r"[\w\s:<>,*&]+\s+(\w+)\s*\((.*)\)\s*{\s*$", line)
    if not m:
        return None
    name = m.group(1)
    params = m.group(2)
    # strip types in params
    if params.strip() == '':
        return f"def {name}():"
    parts = [p.strip() for p in params.split(',') if p.strip()]
    names = []
    for p in parts:
        p = strip_type(p)
        # last token likely name
        toks = p.split()
        if toks:
            names.append(toks[-1])
    return f"def {name}({', '.join(names)}):"


def convert_line(line, types):
    # top-level conversions
    s = line.strip()
    if s in ('{', '}', '};'):
        return ''
    # function defs
    fd = convert_function_def(line)
    if fd:
        return fd
    # main
    if re.match(r"int\s+main\s*\(\s*\)\s*{", s):
        return 'def main():'
    # return
    if re.match(r"return\s+0\s*;", s):
        return 'return'
    if re.match(r"return\s+[^;]+;", s):
        ex = s[len('return'):].strip().rstrip(';')
        return f"return {ex}"
    # declarations
    if re.match(r"^(int|long|long long|string|bool|double|float|char)\b", s):
        d = convert_decl(s, types)
        if d:
            return d
    # cin
    c = convert_cin(s, types)
    if c:
        return c
    # cout
    c2 = convert_cout(s)
    if c2:
        return c2
    # push_back, append
    s = s.replace('push_back(', 'append(')
    s = s.replace('->', '.')
    # vector,map,set
    s = re.sub(r"\bvector<[^>]+>\b", 'list', s)
    s = re.sub(r"\bmap<[^>]+>\b", 'dict', s)
    s = re.sub(r"\bset<[^>]+>\b", 'set', s)
    s = s.replace('st.insert', 'st.add').replace('se.insert', 'se.add')
    s = s.replace('memset(', '# memset:')
    # for
    f = convert_for(s)
    if f:
        return f
    # while
    w = convert_while(s)
    if w:
        py = w[0]
        if w[1]:
            return py + '\n' + '\n'.join(w[1])
        return py
    # getline
    if 'getline(' in s:
        # getline(cin, str);
        m = re.search(r"getline\(\s*cin\s*,\s*(\w+)\s*\)\s*;", s)
        if m:
            return f"{m.group(1)} = input()"
    # getchar
    if s.startswith('getchar(') or s.startswith('getchar();'):
        return "_ = sys.stdin.read(1)"
    # basic expression line: remove semicolon
    if s.endswith(';'):
        return s[:-1]
    return s


def process_file(input_path, output_path, examples_dir=None, max_examples=50):
    input_path = Path(input_path)
    output_path = Path(output_path)
    examples_dir = Path(examples_dir) if examples_dir else None
    if examples_dir:
        examples_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open('r', encoding='utf-8', errors='replace') as inf, \
         output_path.open('w', newline='', encoding='utf-8') as outf:
        reader = csv.DictReader(inf, delimiter='\t')
        fieldnames = reader.fieldnames
        writer = csv.DictWriter(outf, fieldnames=fieldnames, delimiter='\t')
        writer.writeheader()

        types = {}
        program_lines = []
        example_count = 0
        current_key = None

        for row in reader:
            # reset types on new program when 'line' == '0'
            try:
                line_num = int(row.get('line', '0'))
            except:
                line_num = 0
            if line_num == 0:
                types = {}
                # flush previous program to example file if requested
                if examples_dir and program_lines and example_count < max_examples:
                    key = current_key or f"example_{example_count}"
                    p = examples_dir / f"{key}.py"
                    with p.open('w', encoding='utf-8') as pf:
                        pf.write('\n'.join(program_lines))
                    example_count += 1
                program_lines = []
                # compute key
                probid = row.get('probid','')
                subid = row.get('subid','')
                current_key = f"p{probid}_s{subid}" if probid or subid else None

            code = row.get('code','')
            indent = int(row.get('indent','0') or 0)
            py = convert_line(code, types)
            # normalize multi-line conversion: split and apply indentation to each
            out_lines = []
            if py is None:
                py = ''
            for sub in py.split('\n'):
                sub = sub.rstrip()
                if sub == '':
                    out_lines.append('')
                else:
                    out_lines.append((' ' * 4 * indent) + sub)
            py_text = '\n'.join(out_lines)
            # keep text same, replace code
            row['code'] = py_text
            writer.writerow(row)

            # accumulate for example files without the TSV columns
            if examples_dir and py_text.strip() != '':
                program_lines.append(py_text)

        # final flush
        if examples_dir and program_lines and example_count < max_examples:
            key = current_key or f"example_{example_count}"
            p = examples_dir / f"{key}.py"
            with p.open('w', encoding='utf-8') as pf:
                pf.write('\n'.join(program_lines))


def main(argv):
    if len(argv) < 3:
        print('Usage: python tools/cpp_to_py_converter.py <input_tsv> <output_tsv> [--examples N]')
        return 1
    inp = argv[1]
    out = argv[2]
    ex_dir = None
    max_ex = 50
    if '--examples' in argv:
        idx = argv.index('--examples')
        try:
            max_ex = int(argv[idx+1]);
            ex_dir = 'train_py_examples'
        except:
            pass

    process_file(inp, out, examples_dir=ex_dir, max_examples=max_ex)
    print(f'Converted {inp} -> {out}')
    if ex_dir:
        print(f'Wrote example python files to {ex_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

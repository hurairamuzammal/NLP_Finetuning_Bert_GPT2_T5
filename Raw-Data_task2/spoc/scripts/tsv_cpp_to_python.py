#!/usr/bin/env python3
"""
Heuristic converter: convert C/C++ code fragments stored in a TSV into Python-like lines.
Reads: spoc/test/spoc-testp.tsv
Writes: spoc/test/spoc-testp_py.tsv (same columns + code_py)

This is a best-effort, line-by-line translator using regex rules. It won't always produce runnable Python,
but it places Python equivalents and pseudocode in the same row under `code_py`.
"""
import re
import csv
from pathlib import Path

IN = Path(__file__).parent.parent / 'test' / 'spoc-testp.tsv'
OUT = Path(__file__).parent.parent / 'test' / 'spoc-testp_py.tsv'

# Replacement rules: list of (pattern, repl) applied sequentially.
# Many rules use regex and functions for contextual transforms.

# Helper transforms

def repl_types(line):
    # Remove common C++ type keywords but keep structure. Convert vector declarations.
    line = re.sub(r"\b(unsigned long long|unsigned long|unsigned int|long long|long|unsigned|int|double|float|short|size_t|bool)\b", '', line)
    # vector<T> name; -> name = []
    line = re.sub(r"vector<[^>]+>\s*([A-Za-z_][A-Za-z0-9_]*)\s*;", r"\1 = []", line)
    # string s; -> s = ""
    line = re.sub(r"\bstring\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", r"\1 = ''", line)
    # char a[110]; -> a = [''] * 110  (approx)
    line = re.sub(r"char\s+([A-Za-z_][A-Za-z0-9_]*)\s*\[(\d+)\]\s*;", r"\1 = [''] * \2", line)
    # char s[100005]; -> s = ''  (fallback)
    line = re.sub(r"char\s+([A-Za-z_][A-Za-z0-9_]*)\s*\[\d+\]\s*;", r"\1 = ''", line)
    # simple declarations like 'int n, m;' -> 'n = 0; m = 0' -> produce 'n = 0; m = 0'
    m = re.match(r"^\s*(?:int|long|double|float|short)\s+(.+);", line)
    if m:
        rest = m.group(1)
        vars = [v.strip() for v in rest.split(',')]
        assigns = []
        for v in vars:
            # handle 'i = 0' style
            if '=' in v:
                assigns.append(v)
            else:
                name = re.sub(r"\[.*\]", '', v).strip()
                assigns.append(f"{name} = 0")
        return '; '.join(assigns)
    return line


def repl_cout(line):
    # Heuristic: convert cout << ... << ... ; to print(...)
    if 'cout' not in line:
        return line
    s = line.strip()
    # remove trailing ;
    s = s.rstrip(';')
    # remove 'cout << '
    s = s.replace('cout << ', '')
    parts = [p.strip() for p in s.split('<<')]
    # remove possible 'endl' or '\n'
    end_arg = None
    cleaned = []
    for p in parts:
        if p in ('endl', "'\\n'", '"\\n"'):
            end_arg = '\n'
            continue
        cleaned.append(p)
    # If cleaned is empty -> print()
    if not cleaned:
        return 'print()'
    # join by ', '
    expr = ', '.join(cleaned)
    # if original used endl or newline, use print(expr)
    if end_arg is not None:
        return f"print({expr})"
    # If it's printing single character in a loop (like cout << s[i];) we try to avoid newline
    # But we can't know the context; if the original line didn't include endl, use end=''
    if len(cleaned) == 1:
        return f"print({cleaned[0]}, end='')"
    return f"print({expr})"


def repl_cin(line):
    # Convert cin >> var1 >> var2; heuristically
    if 'cin' not in line:
        return line
    s = line.strip().rstrip(';')
    s = s.replace('cin >> ', '')
    parts = [p.strip() for p in s.split('>>') if p.strip()]
    if not parts:
        return '# read input'
    # If there's a single variable, read a token
    if len(parts) == 1:
        v = parts[0]
        # if var looks like array name (a), still use input()
        return f"{v} = input().strip()"
    # multiple variables -> use split()
    vars = ', '.join(parts)
    return f"{vars} = input().split()  # tokens; convert types as needed"


def repl_sizeof(line):
    # replace <container>.size() -> len(<container>)
    line = re.sub(r"([A-Za-z_][A-Za-z0-9_\[\]\.\'\"]*)\.size\(\)", r"len(\1)", line)
    line = re.sub(r"strlen\(([^)]+)\)", r"len(\1)", line)
    # common placeholder functions used in dataset
    line = line.replace('slen()', 'len(s)')
    line = line.replace('tlen()', 'len(t)')
    return line


def repl_for(line):
    # patterns for basic for-loops
    # for (int i = 0; i < n; i++) {
    m = re.match(r"\s*for\s*\(\s*int\s+(\w+)\s*=\s*(\d+)\s*;\s*\1\s*<\s*([^;\)]+)\s*;\s*\1\+\+\s*\)\s*\{?", line)
    if m:
        var, start, end = m.groups()
        # normalize .size() usage inside end
        end = re.sub(r"([A-Za-z_][A-Za-z0-9_\[\]\.\'\"]*)\.size\(\)", r"len(\1)", end)
        return f"for {var} in range({start}, {end}):"
    # decrementing loop: for (int i = s.size() - 1; i >= 0; i--) {
    m = re.match(r"\s*for\s*\(\s*int\s+(\w+)\s*=\s*([^;]+)\s*;\s*\1\s*>=\s*([^;]+)\s*;\s*\1\-\-\s*\)\s*\{?", line)
    if m:
        var, start, end = m.groups()
        # convert container.size() - 1 to len(container)-1
        start = re.sub(r"([A-Za-z_][A-Za-z0-9_\[\]\.\'\"]*)\.size\(\)\s*-\s*1", r"len(\1)-1", start)
        start = re.sub(r"([A-Za-z_][A-Za-z0-9_\[\]\.\'\"]*)\.size\(\)", r"len(\1)", start)
        end = re.sub(r"([A-Za-z_][A-Za-z0-9_\[\]\.\'\"]*)\.size\(\)", r"len(\1)", end)
        # make explicit -1 stop
        return f"for {var} in range({start}, -1, -1):"
    # C-style other forms are left mostly unchanged but with braces removed
    return line


def repl_if(line):
    # replace && -> and, || -> or, == stays, != stays
    line = line.replace('&&', ' and ').replace('||', ' or ')
    # non-greedy match for conditions
    line = re.sub(r"if\s*\((.*?)\)\s*\{?", r"if \1:", line)
    # else if
    line = re.sub(r"else if\s*\((.*?)\)\s*\{?", r"elif \1:", line)
    # else { -> else:
    line = re.sub(r"else\s*\{?", "else:", line)
    return line


def repl_braces(line):
    # remove lone braces
    line = line.replace('{', ':')
    line = line.replace('}', '')
    return line


def repl_pushback(line):
    # ans.push_back(x); -> ans.append(x)
    line = re.sub(r"([A-Za-z_][A-Za-z0-9_]*)\.push_back\((.*)\);", r"\1.append(\2)", line)
    return line


def repl_misc(line):
    line = line.replace('->', '.')
    line = line.replace('::', '.')
    line = line.replace('&&', 'and')
    line = line.replace('||', 'or')
    # boolean literals
    line = re.sub(r"\btrue\b", 'True', line, flags=re.IGNORECASE)
    line = re.sub(r"\bfalse\b", 'False', line, flags=re.IGNORECASE)
    line = line.replace("\tn", '\n')
    # return 0; -> return 0
    line = line.replace('return 0;', 'return 0')
    line = line.replace('return 0;', 'return 0')
    # strip trailing semicolons
    line = re.sub(r";\s*$", '', line)
    # replace slen/tlen placeholders
    line = line.replace('slen()', 'len(s)').replace('tlen()', 'len(t)')
    return line


def convert_line(code, indent):
    # Apply transformations in order
    original = code
    line = code
    line = line.rstrip()
    line = repl_types(line)
    line = repl_sizeof(line)
    # transform for and if/cout/cin specially
    if 'cout' in line:
        line = repl_cout(line)
    if 'cin' in line:
        line = repl_cin(line)
    line = repl_pushback(line)
    # if line starts with for
    if line.strip().startswith('for'):
        line = repl_for(line)
    # if line starts with if or else
    if re.match(r"\s*(if|else if|else)\b", line):
        line = repl_if(line)
    # braces
    line = repl_braces(line)
    line = repl_misc(line)
    # apply indentation spaces according to indent integer
    try:
        ind = int(indent)
    except Exception:
        ind = 0
    py = ('    ' * ind) + line.strip()
    # Return fallback comment if conversion made no change
    if py.strip() == '' and original.strip() != '':
        py = ('    ' * ind) + f"# {original.strip()}"
    return py


def main():
    if not IN.exists():
        print('Input TSV not found:', IN)
        return
    rows = []
    with IN.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f, delimiter='\t')
        headers = reader.fieldnames
        for r in reader:
            rows.append(r)
    # Convert each row
    for r in rows:
        code = r.get('code', '')
        indent = r.get('indent', '0')
        r['code_py'] = convert_line(code, indent)
    # Write out TSV
    out_headers = headers + ['code_py'] if headers else list(rows[0].keys())
    with OUT.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=out_headers, delimiter='\t')
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    print('Wrote', OUT)

if __name__ == '__main__':
    main()

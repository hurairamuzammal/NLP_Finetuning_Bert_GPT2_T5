#!/usr/bin/env python3
import re
import csv
import os

IN = r"c:\Users\Muhammad Abu Huraira\Documents\Assignments and Submissions\Semester 7\NLP\A03\spoc\test\spoc-testp.tsv"
OUT_DIR = os.path.dirname(IN)

# Conservative translation rules for many common C++ snippets found in the TSV.
# This script focuses on per-line textual replacement for the "code" (2nd) column.
# It is intentionally conservative (keeps non-matching lines unchanged) to avoid
# introducing errors.

def translate_code(code):
    if code is None:
        return ''
    s = code.strip()
    if s == '':
        return s

    # Normalize some common whitespace patterns
    s = s.replace('\t', ' ').strip()

    # int main() {  -> def main():
    if re.match(r'^int\s+main\s*\(\s*\)\s*\{?$', s):
        return 'def main():'

    # return 0; -> return 0
    if s == 'return 0;' or s == 'return 0;':
        return 'return 0'

    # opening/closing braces - drop them (structure not preserved in TSV row-level)
    if s == '{' or s == '}':
        return ''

    # simple declaration translations
    m = re.match(r'^string\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$', s)
    if m:
        return f"{m.group(1)} = ''"

    m = re.match(r'^char\s+([A-Za-z_][A-Za-z0-9_]*)\[[0-9]+\]\s*;$', s)
    if m:
        return f"{m.group(1)} = ''"

    m = re.match(r'^(?:int|long\s+long|long|short\s+int|short)\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$', s)
    if m:
        return f"{m.group(1)} = 0"

    m = re.match(r'^bool\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*false\s*;?$', s)
    if m:
        return f"{m.group(1)} = False"
    m = re.match(r'^bool\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*true\s*;?$', s)
    if m:
        return f"{m.group(1)} = True"

    # vector declarations
    m = re.match(r'^vector<\s*char\s*>\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$', s)
    if m:
        return f"{m.group(1)} = []"
    m = re.match(r'^vector<\s*string\s*>\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$', s)
    if m:
        return f"{m.group(1)} = []"
    m = re.match(r'^vector<\s*int\s*>\s+([A-Za-z_][A-Za-z0-9_]*)\s*;$', s)
    if m:
        return f"{m.group(1)} = []"

    # push_back -> append
    s = re.sub(r'\.push_back\s*\(', '.append(', s)

    # cin >> var1 >> var2;  -> var1, var2 = input().split()
    if s.startswith('cin >>'):
        body = s[len('cin >>'):].strip().rstrip(';')
        vars = [v.strip() for v in body.split('>>') if v.strip()]
        if len(vars) == 1:
            return f"{vars[0]} = input().strip()"
        else:
            return f"{', '.join(vars)} = input().split()"

    # getline(cin, var); or cin.getline(var, SIZE); -> var = input()
    m = re.match(r'^getline\(\s*cin\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*;?$', s)
    if m:
        return f"{m.group(1)} = input()"
    m = re.match(r'^cin\.getline\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*[0-9]+\s*\)\s*;?$', s)
    if m:
        return f"{m.group(1)} = input()"

    # cout patterns
    if s.startswith('cout <<'):
        body = s[len('cout <<'):].strip().rstrip(';')
        # split by '<<' and strip
        parts = [p.strip() for p in re.split(r'<<', body) if p.strip()]
        # detect endl or '\n'
        if any('endl' in p or "'\\n'" in p or '"\\n"' in p for p in parts):
            # remove endl parts
            parts = [p for p in parts if 'endl' not in p and "'\\n'" not in p and '"\\n"' not in p]
            if len(parts) == 0:
                return 'print()'
            elif len(parts) == 1:
                return f"print({parts[0]})"
            else:
                return f"print({', '.join(parts)})"
        else:
            # no newline -> print with end=''
            if len(parts) == 1:
                return f"print({parts[0]}, end='')"
            else:
                return f"print({', '.join(parts)}, end='')"

    # simple if/else/elif conversions (strip trailing braces)
    m = re.match(r'^if\s*\((.*)\)\s*\{?$', s)
    if m:
        cond = m.group(1).strip()
        cond = cond.replace('&&', ' and ').replace('||', ' or ').replace('==', ' == ').replace('!=', ' != ')
        cond = cond.replace('!',' not ')
        return f"if {cond}:"

    m = re.match(r'^else\s+if\s*\((.*)\)\s*\{?$', s)
    if m:
        cond = m.group(1).strip()
        cond = cond.replace('&&', ' and ').replace('||', ' or ')
        return f"elif {cond}:"

    if re.match(r'^else\s*\{?$', s):
        return 'else:'

    # break/continue
    if s == 'break;' :
        return 'break'
    if s == 'continue;' :
        return 'continue'

    # for loops (common patterns)
    m = re.match(r'^for\s*\(\s*int\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([0-9+-]+)\s*;\s*\1\s*<\s*([A-Za-z0-9_\.\(\)\-\+]+)\s*;\s*\1\+\+\s*\)\s*\{?$', s)
    if m:
        i, start, end = m.group(1), m.group(2), m.group(3)
        return f"for {i} in range({start}, {end}):"
    m = re.match(r'^for\s*\(\s*int\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z0-9_\(\)\-\+]+)\s*;\s*\1\s*>=\s*([0-9]+)\s*;\s*\1--\s*\)\s*\{?$', s)
    if m:
        i, start, end = m.group(1), m.group(2), m.group(3)
        return f"for {i} in range({start}, {end}-1, -1):"

    # replace C++ true/false tokens
    s = s.replace('true', 'True').replace('false', 'False')

    # semi-colon removal for simple statements
    if s.endswith(';'):
        s = s[:-1]

    return s


def write_chunk(lines, out_path):
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        f.write(header_line + '\n')
        for ln in lines:
            # parse TSV columns robustly
            cols = ln.split('\t')
            if len(cols) >= 2:
                cols[1] = translate_code(cols[1])
            f.write('\t'.join(cols) + '\n')


if __name__ == '__main__':
    with open(IN, 'r', encoding='utf-8') as fh:
        all_lines = [l.rstrip('\n') for l in fh]

    if not all_lines:
        print('Input file empty')
        raise SystemExit(1)

    header_line = all_lines[0]
    data_lines = all_lines[1:]
    total = len(data_lines)
    chunk_size = total // 4
    remainder = total % 4

    indices = []
    start = 0
    for i in range(4):
        add = chunk_size + (1 if i < remainder else 0)
        end = start + add
        indices.append((start, end))
        start = end

    for idx, (s_idx, e_idx) in enumerate(indices, start=1):
        out_name = os.path.join(OUT_DIR, f"spoc-testp_py_chunk{idx}.tsv")
        write_chunk(data_lines[s_idx:e_idx], out_name)
        print(f'Wrote {out_name} with {e_idx - s_idx} data lines')

    print('Done')

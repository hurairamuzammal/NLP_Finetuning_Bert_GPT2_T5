import csv
import json

def convert_tsv_to_jsonl(input_file, output_file):
    """
    Convert TSV file to JSONL format.
    Each line in the JSONL file will be a JSON object with the TSV columns.
    """
    with open(input_file, 'r', encoding='utf-8') as tsv_file, \
         open(output_file, 'w', encoding='utf-8') as jsonl_file:
        
        # Read TSV file
        reader = csv.DictReader(tsv_file, delimiter='\t')
        
        # Convert each row to JSON and write to JSONL file
        count = 0
        for row in reader:
            # Convert to JSON and write as a single line
            json_line = json.dumps(row, ensure_ascii=False)
            jsonl_file.write(json_line + '\n')
            count += 1
            
            # Print progress every 10000 lines
            if count % 10000 == 0:
                print(f"Processed {count} lines...")
        
        print(f"\nConversion complete! Total lines: {count}")
        print(f"Output file: {output_file}")

if __name__ == "__main__":
    input_file = "spoc-train-py.tsv"
    output_file = "spoc-train-py.jsonl"
    
    print(f"Converting {input_file} to {output_file}...")
    convert_tsv_to_jsonl(input_file, output_file)

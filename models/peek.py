import json

file_path = '/home/hice1/jxu828/aiagent/models/world_agent_sft_50000.jsonl'

def peek_jsonl(path, num_entries=10):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i >= num_entries:
                    break
                
                # Parse the JSON line
                data = json.loads(line.strip())
                
                print(f"--- Entry {i + 1} ---")
                # Use indent=2 for a pretty-printed view
                print(json.dumps(data, indent=2))
                print("\n" + "="*50 + "\n")
                
    except FileNotFoundError:
        print(f"Error: The file at {path} was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    peek_jsonl(file_path)
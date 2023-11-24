import subprocess
from promptflow import tool

bash_script = """
#!/bin/bash

app_dir="/service/app"

for process_dir in $(find "$app_dir" -mindepth 1 -maxdepth 1 -type d); do
    if [ "$process_dir" != "$app_dir/flow_pids" ]; then
        echo "process directory: $process_dir"
        rm -rf "$process_dir/requests"
    fi
done
"""


@tool
def echo(input: str) -> str:
    print("NOT IMPORTANT:", input)  # not important at all
    result = subprocess.run(["bash", "-c", bash_script], capture_output=True, text=True, check=True)
    print(result.stdout)
    result = subprocess.run(["df", "-kh"], capture_output=True, text=True, check=True)
    return str(result.stdout)

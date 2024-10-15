import pychrome
import os
import re
import time
from rich.console import Console
from rich.panel import Panel
from datetime import datetime
import json
import nltk
from nltk.tokenize import sent_tokenize
from collections import OrderedDict
nltk.download('punkt')

### Before running this script:
# 1. Make sure you have installed packages from requirements.txt
# 2. Make sure you have installed Google Chrome
# 3. Make sure you have you have run this command to start chrome in debug mode:
# "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:/Users/<User>/AppData/Local/Google/Chrome/User Data"


# Global variables to store tabs
browser = None
tabs = {}

def initialize_browser():
    global browser, tabs
    browser = pychrome.Browser(url="http://127.0.0.1:9222")

    # Get list of open tabs
    existing_tabs = browser.list_tab()

    tab = browser.new_tab()
    tab.start()
    tab.Network.enable()
    tab.Page.enable()
    tab.Runtime.enable()
    tab.DOM.enable()
    for tab in existing_tabs:
        browser.close_tab(tab)
    # URLs for each model
    urls = {
        "o1-preview": "https://chat.openai.com/?model=o1-preview",
        "o1-mini": "https://chat.openai.com/?model=o1-mini",
        "gpt-4o": "https://chat.openai.com/?model=gpt-4o",
    }
    # Open tabs for each model
    for model_name, url in urls.items():
        tab = browser.new_tab()
        tab.start()
        tab.Network.enable()
        tab.Page.enable()
        tab.Runtime.enable()
        tab.DOM.enable()
        tab.Page.navigate(url=url)
        # Wait for the page to load
        time.sleep(2)
        tabs[model_name] = tab

    # Check if login is required
    current_url = tabs["o1-preview"].Runtime.evaluate(
        expression="window.location.href"
    )["result"]["value"]
    if "login" in current_url or "auth0" in current_url:
        input(
            "Please log in to ChatGPT in the opened browser tabs, then press Enter here to continue..."
        )

def remove_duplicate_sentences(text, case_sensitive=False):
    # Tokenize the text into sentences
    sentences = sent_tokenize(text)

    # Initialize an ordered dictionary to preserve the order of sentences
    unique_sentences = OrderedDict()

    for sentence in sentences:
        # Normalize sentence based on case sensitivity
        key = sentence if case_sensitive else sentence.lower()

        if key not in unique_sentences:
            unique_sentences[key] = sentence  # Preserve the original sentence

    # Join the unique sentences back into a single string
    cleaned_text = ' '.join(unique_sentences.values())

    return cleaned_text

def wait_for_selector(tab, selector):
    result = tab.Runtime.evaluate(
        expression=f"document.querySelector('{selector}') != null"
    )["result"]["value"]
    while not result:
        time.sleep(0.5)
        result = tab.Runtime.evaluate(
            expression=f"document.querySelector('{selector}') != null"
        )["result"]["value"]


def insert_prompt(tab, prompt):
    browser.activate_tab(tab)
    # Focus on the textarea
    tab.Runtime.evaluate(
        expression="document.querySelector('#prompt-textarea').focus()"
    )

    # Insert the prompt
    tab.call_method("Input.insertText", text=prompt)

    # Press Enter to submit the prompt
    enter_key_event = {
        "type": "keyDown",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
        "macCharCode": 13,
        "unmodifiedText": "\r",
        "text": "\r",
        "key": "Enter",
        "code": "Enter",
        "nativeKeyCode": 13,
    }
    tab.call_method("Input.dispatchKeyEvent", **enter_key_event)
    enter_key_event["type"] = "keyUp"
    tab.call_method("Input.dispatchKeyEvent", **enter_key_event)


def get_response(tab, timeout=120):
    previous_text = ""
    start_time = time.time()
    while True:
        # JavaScript to check if the assistant has responded
        check_response_js = """
        (() => {
            // Select all message containers
            const messages = document.querySelectorAll('div[class*="markdown"]');
            const lastMessage = messages[messages.length - 1];

            if (lastMessage) {
                return lastMessage.textContent.trim();
            }
            return null;
        })();
        """
        result = tab.Runtime.evaluate(expression=check_response_js)
        response_text = result.get("result", {}).get("value", None)
        if response_text:
            if previous_text == response_text:
                return response_text
            previous_text = response_text
            time.sleep(10)
        elif time.time() - start_time > timeout:
            raise TimeoutError("Waiting for response timed out.")
        else:
            time.sleep(5)  # Check every 5 seconds


# Initialize the Rich Console for enhanced terminal output
console = Console()


def gpt_orchestrator(
    objective, file_content=None, previous_results=None, use_search=False
):
    console.print(f"\n[bold]Calling Orchestrator for your objective[/bold]")
    previous_results_text = "\n".join(previous_results) if previous_results else "None"

    if file_content:
        console.print(
            Panel(
                f"File content:\n{file_content}",
                title="[bold blue]File Content[/bold blue]",
                title_align="left",
                border_style="blue",
            )
        )

    # Construct the prompt
    prompt = (
        f"Based on the following objective{' and file content' if file_content else ''}, and the previous sub-task results (if any), please break down the objective into the next sub-task, and create a concise and detailed prompt for a subagent so it can execute that task. IMPORTANT!!! when dealing with code tasks make sure you check the code for errors and provide fixes and support as part of the next sub-task. If you find any bugs or have suggestions for better code, please include them in the next sub-task prompt. Please assess if the objective has been fully achieved. If the previous sub-task results comprehensively address all aspects of the objective, include the phrase 'The task is complete:' at the beginning of your response. If the objective is not yet fully achieved, break it down into the next sub-task and create a concise and detailed prompt for a subagent to execute that task.:\n\nObjective: {objective}"
        + (f"\nFile content:\n{file_content}" if file_content else "")
        + f"\n\nPrevious sub-task results:\n{previous_results_text}"
    )
    remove_duplicate_sentences(prompt)
    # Use the 'o1-mini' model tab
    tab = tabs["o1-mini"]

    # Wait for the prompt textarea to be available
    wait_for_selector(tab, "#prompt-textarea")

    # Insert the prompt and submit
    insert_prompt(tab, prompt)

    # Retrieve the response
    try:
        response_text = get_response(tab)
        console.print(
            Panel(
                response_text,
                title=f"[bold green]GPT Orchestrator[/bold green]",
                title_align="left",
                border_style="green",
                subtitle="Sending task to GPT 👇",
            )
        )
        console.print()
    except TimeoutError as e:
        console.print(
            Panel(
                str(e),
                title="[bold red]Error[/bold red]",
                title_align="left",
                border_style="red",
            )
        )
        response_text = ""

    # Process search query if use_search is True
    search_query = None
    if use_search:
        # Attempt to extract the JSON search query from the response
        json_match = re.search(r"{.*}", response_text, re.DOTALL)
        if json_match:
            json_string = json_match.group()
            try:
                search_query = json.loads(json_string)["search_query"]
                console.print(
                    Panel(
                        f"Search Query: {search_query}",
                        title="[bold blue]Search Query[/bold blue]",
                        title_align="left",
                        border_style="blue",
                    )
                )
                # Remove the JSON part from the response text
                response_text = response_text.replace(json_string, "").strip()
            except json.JSONDecodeError as e:
                console.print(
                    Panel(
                        f"Error parsing JSON: {e}",
                        title="[bold red]JSON Parsing Error[/bold red]",
                        title_align="left",
                        border_style="red",
                    )
                )
                console.print(
                    Panel(
                        f"Skipping search query extraction.",
                        title="[bold yellow]Search Query Extraction Skipped[/bold yellow]",
                        title_align="left",
                        border_style="yellow",
                    )
                )
        else:
            search_query = None

    return response_text, file_content, search_query


def gpt_sub_agent(
    prompt,
    search_query=None,
    previous_gpt_tasks=None,
    use_search=False,
    continuation=False,
):
    if previous_gpt_tasks is None:
        previous_gpt_tasks = []

    # Define a prompt for continuing previous answers if needed
    continuation_prompt = (
        "Continuing from the previous answer, please complete the response."
    )

    # Construct system message with previous tasks
    system_message = "Previous GPT tasks:\n" + "\n".join(
        f"Task: {task['task']}\nResult: {task['result']}" for task in previous_gpt_tasks
    )

    # Use the continuation prompt if this is a continuation
    if continuation:
        prompt = continuation_prompt

    qna_response = None
    # Include search results in the prompt if available
    if qna_response:
        prompt += f"\nSearch Results:\n{qna_response}"

    # Include system message
    full_prompt = f"{system_message}\n\n{prompt}"

    # Use the 'gpt-4o' model tab
    tab = tabs["gpt-4o"]

    # Wait for the prompt textarea to be available
    wait_for_selector(tab, "#prompt-textarea")

    # Insert the prompt and submit
    insert_prompt(tab, full_prompt)

    # Retrieve the response
    try:
        response_text = get_response(tab)
        console.print(
            Panel(
                response_text,
                title="[bold blue]GPT Sub-agent Result[/bold blue]",
                title_align="left",
                border_style="blue",
                subtitle="Task completed, sending result to GPT 👇",
            )
        )
        console.print()
    except TimeoutError as e:
        console.print(
            Panel(
                str(e),
                title="[bold red]Error[/bold red]",
                title_align="left",
                border_style="red",
            )
        )
        response_text = ""

    # Check if the output is too long and needs continuation
    # You can implement logic here if necessary

    return response_text


def gpt_refine(objective, sub_task_results, filename, projectname, continuation=False):
    console.print(
        "\nCalling GPT to provide the refined final output for your objective:"
    )

    # Construct the prompt
    prompt = (
        f"Objective: {objective}\n\nSub-task results:\n"
        + "\n".join(sub_task_results)
        + "\n\nPlease review and refine the sub-task results into a cohesive final output. Add any missing information or details as needed. When working on code projects, ONLY AND ONLY IF THE PROJECT IS CLEARLY A CODING ONE please provide the following:\n1. Project Name: Create a concise and appropriate project name that fits the project based on what it's creating. The project name should be no more than 20 characters long.\n2. Folder Structure: Provide the folder structure as a valid JSON object, where each key represents a folder or file, and nested keys represent subfolders. Use null values for files. Ensure the JSON is properly formatted without any syntax errors. Please make sure all keys are enclosed in double quotes, and ensure objects are correctly encapsulated with braces, separating items with commas as necessary.\nWrap the JSON object in <folder_structure> tags.\n3. Code Files: For each code file, include ONLY the file name NEVER EVER USE THE FILE PATH OR ANY OTHER FORMATTING YOU ONLY USE THE FOLLOWING format 'Filename: <filename>' followed by the code block enclosed in triple backticks, with the language identifier after the opening backticks, like this:\n\npython\n<code>\n"
    )
    remove_duplicate_sentences(prompt)
    # Use the 'o1-preview' model tab
    tab = tabs["o1-preview"]

    # Wait for the prompt textarea to be available
    wait_for_selector(tab, "#prompt-textarea")

    # Insert the prompt and submit
    insert_prompt(tab, prompt)

    # Retrieve the response
    try:
        response_text = get_response(tab)
        console.print(
            Panel(
                response_text,
                title="[bold green]GPT Refine Result[/bold green]",
                title_align="left",
                border_style="green",
                subtitle="Refinement complete 👇",
            )
        )
        console.print()
    except TimeoutError as e:
        console.print(
            Panel(
                str(e),
                title="[bold red]Error[/bold red]",
                title_align="left",
                border_style="red",
            )
        )
        response_text = ""

    # Check if the output is too long and needs continuation
    # Implement continuation logic if necessary

    return response_text


def create_folder_structure(project_name, folder_structure, code_blocks):
    try:
        # Create the main project directory
        os.makedirs(project_name, exist_ok=True)
        console.print(
            Panel(
                f"Created project folder: [bold]{project_name}[/bold]",
                title="[bold green]Project Folder[/bold green]",
                title_align="left",
                border_style="green",
            )
        )
    except OSError as e:
        # Handle errors during folder creation
        console.print(
            Panel(
                f"Error creating project folder: [bold]{project_name}[/bold]\nError: {e}",
                title="[bold red]Project Folder Creation Error[/bold red]",
                title_align="left",
                border_style="red",
            )
        )
        return

    # Recursively create subfolders and files
    create_folders_and_files(project_name, folder_structure, code_blocks)


def create_folders_and_files(current_path, structure, code_blocks):
    for key, value in structure.items():
        path = os.path.join(current_path, key)
        if isinstance(value, dict):
            try:
                # Create subfolder
                os.makedirs(path, exist_ok=True)
                console.print(
                    Panel(
                        f"Created folder: [bold]{path}[/bold]",
                        title="[bold blue]Folder Creation[/bold blue]",
                        title_align="left",
                        border_style="blue",
                    )
                )
                # Recursively create nested folders/files
                create_folders_and_files(path, value, code_blocks)
            except OSError as e:
                # Handle errors during folder creation
                console.print(
                    Panel(
                        f"Error creating folder: [bold]{path}[/bold]\nError: {e}",
                        title="[bold red]Folder Creation Error[/bold red]",
                        title_align="left",
                        border_style="red",
                    )
                )
        else:
            # Handle file creation
            code_content = next(
                (code for file, code in code_blocks if file == key), None
            )
            if code_content:
                try:
                    # Write the code content to the file
                    with open(path, "w") as file:
                        file.write(code_content)
                    console.print(
                        Panel(
                            f"Created file: [bold]{path}[/bold]",
                            title="[bold green]File Creation[/bold green]",
                            title_align="left",
                            border_style="green",
                        )
                    )
                except IOError as e:
                    # Handle errors during file creation
                    console.print(
                        Panel(
                            f"Error creating file: [bold]{path}[/bold]\nError: {e}",
                            title="[bold red]File Creation Error[/bold red]",
                            title_align="left",
                            border_style="red",
                        )
                    )
            else:
                # Notify if code content for the file is missing
                console.print(
                    Panel(
                        f"Code content not found for file: [bold]{key}[/bold]",
                        title="[bold yellow]Missing Code Content[/bold yellow]",
                        title_align="left",
                        border_style="yellow",
                    )
                )


def read_file(file_path):
    with open(file_path, "r") as file:
        content = file.read()
    return content


# Prompt the user to enter their main objective
objective = input("Please enter your objective: ")

# Ask the user if they want to provide a file path
provide_file = input("Do you want to provide a file path? (y/n): ").lower() == "y"

if provide_file:
    # If user chooses to provide a file, get the file path
    file_path = input("Please enter the existing file path: ")
    if os.path.exists(file_path):
        # Read the file content if the file exists
        file_content = read_file(file_path)
    else:
        # Notify the user if the file is not found
        print(f"File not found: {file_path}")
        file_content = None
else:
    file_content = None

# Ask the user if they want to use search functionality
# use_search = input("Do you want to use search? (y/n): ").lower() == 'y'

# Initialize lists to keep track of task exchanges and GPT tasks
task_exchanges = []
gpt_tasks = []
initialize_browser()
use_search = False
# Main loop to orchestrate tasks until completion
while True:
    # Gather previous results from task exchanges
    previous_results = [result for _, result in task_exchanges]

    if not task_exchanges:
        # If no tasks have been executed yet, call the orchestrator with the objective and file content
        gpt_result, file_content_for_gpt, search_query = gpt_orchestrator(
            objective, file_content, previous_results, use_search
        )
    else:
        # For subsequent iterations, call the orchestrator with previous results
        gpt_result, _, search_query = gpt_orchestrator(
            objective, previous_results=previous_results, use_search=use_search
        )

    if "The task is complete:" in gpt_result:
        # If the orchestrator indicates completion, extract the final output
        final_output = gpt_result.replace("The task is complete:", "").strip()
        break
    else:
        # Otherwise, treat the result as a sub-task prompt
        sub_task_prompt = gpt_result
        if file_content_for_gpt and not gpt_tasks:
            # Include file content in the first sub-task if available
            sub_task_prompt = (
                f"{sub_task_prompt}\n\nFile content:\n{file_content_for_gpt}"
            )
        # Execute the sub-task using the GPT sub-agent
        sub_task_result = gpt_sub_agent(
            sub_task_prompt, search_query, gpt_tasks, use_search
        )
        # Record the sub-task and its result
        gpt_tasks.append({"task": sub_task_prompt, "result": sub_task_result})
        task_exchanges.append((sub_task_prompt, sub_task_result))
        # Reset file content after first use
        file_content_for_gpt = None

# Sanitize the objective to create a valid filename
sanitized_objective = re.sub(r"\W+", "_", objective)
# Generate a timestamp for logging
timestamp = datetime.now().strftime("%H-%M-%S")
# Refine the final output using the Anthropic model
refined_output = gpt_refine(
    objective, [result for _, result in task_exchanges], timestamp, sanitized_objective
)

# Extract the project name from the refined output using regex
project_name_match = re.search(r"Project Name: (.*)", refined_output)
project_name = (
    project_name_match.group(1).strip() if project_name_match else sanitized_objective
)

# Extract the folder structure JSON from the refined output
folder_structure_match = re.search(
    r"<folder_structure>(.*?)</folder_structure>", refined_output, re.DOTALL
)
folder_structure = {}
if folder_structure_match:
    json_string = folder_structure_match.group(1).strip()
    try:
        folder_structure = json.loads(json_string)
    except json.JSONDecodeError as e:
        # Handle JSON parsing errors
        console.print(
            Panel(
                f"Error parsing JSON: {e}",
                title="[bold red]JSON Parsing Error[/bold red]",
                title_align="left",
                border_style="red",
            )
        )
        console.print(
            Panel(
                f"Invalid JSON string: [bold]{json_string}[/bold]",
                title="[bold red]Invalid JSON String[/bold red]",
                title_align="left",
                border_style="red",
            )
        )

# Extract code blocks (filenames and their corresponding code) using regex
code_blocks = re.findall(r"Filename: (\S+)\s*[\w]*\n(.*?)\n", refined_output, re.DOTALL)
# Create the folder structure and files based on the extracted information
create_folder_structure(project_name, folder_structure, code_blocks)

# Truncate the objective for the log filename if necessary
max_length = 25
truncated_objective = (
    sanitized_objective[:max_length]
    if len(sanitized_objective) > max_length
    else sanitized_objective
)

# Generate a filename for the exchange log
filename = f"{timestamp}_{truncated_objective}.md"

# Initialize the exchange log with the objective
exchange_log = f"Objective: {objective}\n\n"
exchange_log += "=" * 40 + " Task Breakdown " + "=" * 40 + "\n\n"

# Append each task and its result to the exchange log
for i, (prompt, result) in enumerate(task_exchanges, start=1):
    exchange_log += f"Task {i}:\n"
    exchange_log += f"Prompt: {prompt}\n"
    exchange_log += f"Result: {result}\n\n"

# Append the refined final output to the exchange log
exchange_log += "=" * 40 + " Refined Final Output " + "=" * 40 + "\n\n"
exchange_log += refined_output

# Display the refined final output in the console
console.print(f"\n[bold]Refined Final output:[/bold]\n{refined_output}")

# Save the full exchange log to a markdown file
with open(filename, "w") as file:
    file.write(exchange_log)
print(f"\nFull exchange log saved to {filename}")
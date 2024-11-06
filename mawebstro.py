import pychrome
import os
import sys
import re
import time
import json
import subprocess
import argparse
from rich.console import Console
from rich.panel import Panel
from datetime import datetime
import json

### Before running this script:
# 1. Make sure you have installed packages from requirements.txt
# 2. Make sure you have installed Google Chrome
# 3. Make sure you have you have run this command to start chrome in debug mode:
# "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:/Users/<User>/AppData/Local/Google/Chrome/User Data"


# Initialize the Rich Console for enhanced terminal output
console = Console()

# Global variables to store tabs
browser = None
tabs = {}

def is_chrome_running_in_debug_mode():
    # Check if Chrome is running in debug mode
    try:
        browser = pychrome.Browser(url="http://127.0.0.1:9222")
        browser.list_tab()
        return True
    except Exception:
        return False

def start_chrome_in_debug_mode():
    # Attempt to start Chrome in debug mode automatically
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"/usr/bin/google-chrome",
        r"/usr/bin/chromium-browser",
    ]

    chrome_path = next((path for path in chrome_paths if os.path.exists(path)), None)

    if not chrome_path:
        console.print("[bold red]Google Chrome executable not found.[/bold red]")
        sys.exit(1)

    user_data_dir = os.path.join(os.getcwd(), "chrome_user_data")
    os.makedirs(user_data_dir, exist_ok=True)

    try:
        subprocess.Popen([
            chrome_path,
            "--remote-debugging-port=9222",
            f'--user-data-dir="{user_data_dir}"',
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-popup-blocking",
            "--disable-extensions",
        ])
        console.print("[bold green]Started Chrome in debug mode.[/bold green]")
        time.sleep(5)  # Wait for Chrome to start
    except Exception as e:
        console.print(f"[bold red]Failed to start Chrome in debug mode: {e}[/bold red]")
        sys.exit(1)

def initialize_browser():
    global browser, tabs
    browser = pychrome.Browser(url="http://127.0.0.1:9222")

    # Close any existing tabs
    existing_tabs = browser.list_tab()
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
        console.print("[bold yellow]Please log in to ChatGPT in the opened browser tabs.[/bold yellow]")
        input("After logging in, press Enter here to continue...")

def wait_for_selector(tab):
    result = tab.Runtime.evaluate(
        expression=f"document.querySelector('#prompt-textarea') !== null"
    )["result"]["value"]
    while not result:
        time.sleep(0.5)
        result = tab.Runtime.evaluate(
            expression=f"document.querySelector('#prompt-textarea') !== null"
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
    tab.call_method("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", text="\r")
    tab.call_method("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", text="\r")

def get_response(tab, timeout=120):
    previous_text = ""
    start_time = time.time()
    while True:
        # JavaScript to check if the assistant has responded
        check_response_js = """
        (() => {
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

def gpt_orchestrator(objective):
    console.print(f"\n[bold]Calling Orchestrator for your objective[/bold]")

    # Construct the prompt
    prompt = (
        f"Based on the following objective, please break down the objective into the next sub-task, and create a concise and detailed prompt for a subagent so it can execute that task. "
        f"If the objective has been fully achieved, include the phrase 'The task is complete:' at the beginning of your response.\n\nObjective: {objective}"
    )

    # Use the 'o1-mini' model tab
    tab = tabs["o1-mini"]

    # Wait for the prompt textarea to be available
    wait_for_selector(tab)

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

    return response_text

def gpt_sub_agent(sub_task_prompt):
    # Use the 'gpt-4o' model tab
    tab = tabs["gpt-4o"]

    # Wait for the prompt textarea to be available
    wait_for_selector(tab)

    # Insert the prompt and submit
    insert_prompt(tab, sub_task_prompt)

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

    return response_text

def gpt_refine(objective):
    console.print(
        "\nCalling GPT to provide the refined final output for your objective:"
    )

    # Construct the prompt
    prompt = (
        f"Objective: {objective}\n\nPlease review and refine the sub-task results into a cohesive final output. Add any missing information or details as needed. When working on code projects, ONLY AND ONLY IF THE PROJECT IS CLEARLY A CODING ONE please provide the following:\n1. Project Name: Create a concise and appropriate project name that fits the project based on what it's creating. The project name should be no more than 20 characters long.\n2. Folder Structure: Provide the folder structure as a valid JSON object, where each key represents a folder or file, and nested keys represent subfolders. Use null values for files. Ensure the JSON is properly formatted without any syntax errors. Please make sure all keys are enclosed in double quotes, and ensure objects are correctly encapsulated with braces, separating items with commas as necessary.\nWrap the JSON object in <folder_structure> tags.\n3. Code Files: For each code file, include ONLY the file name NEVER EVER USE THE FILE PATH OR ANY OTHER FORMATTING YOU ONLY USE THE FOLLOWING format 'Filename: <filename>' followed by the code block enclosed in triple backticks, with the language identifier after the opening backticks, like this:\n\npython\n<code>\n"
        f"If applicable, provide code files and folder structures as per best practices."
    )

    # Use the 'o1-preview' model tab
    tab = tabs["o1-preview"]

    # Wait for the prompt textarea to be available
    wait_for_selector(tab)

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

    return response_text

def main():
    parser = argparse.ArgumentParser(description="GPT Assistant Application")
    parser.add_argument('-o', '--objective', type=str, help='Your objective or the path to a file containing it')
    args = parser.parse_args()

    if not args.objective:
        console.print("[bold red]Please provide an objective using the -o or --objective flag.[/bold red]")
        sys.exit(1)

    user_input = args.objective

    # Check if the input is a file path
    if os.path.isfile(user_input):
        try:
            with open(user_input, 'r') as file:
                objective = file.read().strip()
        except Exception as e:
            console.print(f"[bold red]An error occurred while reading the file: {e}[/bold red]")
            sys.exit(1)
    else:
        objective = user_input

    if not is_chrome_running_in_debug_mode():
        start_chrome_in_debug_mode()

    # Initialize the browser tabs
    initialize_browser()

    # Main loop to orchestrate tasks until completion
    while True:
        # Call the orchestrator with the objective
        gpt_result = gpt_orchestrator(objective)

        if "The task is complete:" in gpt_result:
            # If the orchestrator indicates completion, extract the final output
            objective = gpt_result.replace("The task is complete:", "").strip()
            break
        else:
            # Otherwise, treat the result as a sub-task prompt
            sub_task_prompt = gpt_result
            # Execute the sub-task using the GPT sub-agent
            sub_task_result = gpt_sub_agent(sub_task_prompt)
            # Update the objective with the sub-task result for the next iteration
            objective = sub_task_result

    # Refine the final output using the GPT refine function
    refined_output = gpt_refine(objective)

    # Write the refined output to a file with a timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"output_{timestamp}.md"
    with open(output_filename, "w", encoding='utf-8') as file:
        file.write(refined_output)
    console.print(f"[bold green]Refined output written to {output_filename}[/bold green]")

if __name__ == "__main__":
    main()

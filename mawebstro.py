import pychrome
import os
import sys
import time
import json
import subprocess
import argparse
from datetime import datetime
import shutil
import tempfile

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

user_data_dir = ""

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
        sys.exit("Google Chrome executable not found.")

    try:
        subprocess.Popen([
            chrome_path,
            "--remote-debugging-port=9222",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-popup-blocking",
            "--disable-extensions",
        ])
        time.sleep(2)  # Wait for Chrome to start
    except Exception as e:
        sys.exit(f"Failed to start Chrome in debug mode: {e}")

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
    )["result"].get("value", "")
    if "login" in current_url or "auth0" in current_url:
        input("Please log in to ChatGPT in the opened browser tabs. After logging in, press Enter here to continue...")

def wait_for_selector(tab):
    result = tab.Runtime.evaluate(
        expression=f"document.querySelector('#prompt-textarea') !== null"
    )["result"].get("value", False)
    while not result:
        time.sleep(0.5)
        result = tab.Runtime.evaluate(
            expression=f"document.querySelector('#prompt-textarea') !== null"
        )["result"].get("value", False)

def gpt_interact(tab, prompt, update_interval=4, timeout=120):
    # Wait for the prompt textarea to be available
    wait_for_selector(tab)

    # Insert the prompt and submit
    browser.activate_tab(tab)
    tab.Runtime.evaluate(
        expression="document.querySelector('#prompt-textarea').focus()"
    )
    tab.call_method("Input.insertText", text=prompt)
    tab.call_method("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", text="\r")
    tab.call_method("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", text="\r")

    # Retrieve the response
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
        elapsed_time = time.time() - start_time
        if elapsed_time > timeout:
          raise TimeoutError("Waiting for response timed out.")
        else:
            time.sleep(update_interval)  # Check every n seconds

def gpt_orchestrator(objective):
    global is_first_call

    # Construct the prompt
    if is_first_call:
        prompt = (
            f"Objective: {objective}\n\n"
            f"Break down the objective into a list of small but important and meaningful sub-tasks to achieve the goal."
        )
        is_first_call = False
    else:
        prompt = (
            f"Objective: {objective}\n"
            "Identify the next small but important sub-task that needs to be done. Include short dictionary-like summary of context, previous completed sub-task, and if required add clarifications, and generate a concise, well-detailed prompt for a sub-agent to execute the task."
            "IF AND ONLY IF ALL SUB-TASKS ARE FINISHED, include 'The task is complete:' at the beginning."
        )

    # Use the 'o1-mini' model tab
    tab = tabs.get("o1-mini")
    if tab is None:
        return ""

    # Interact with GPT
    try:
        response_text = gpt_interact(tab, prompt)
    except TimeoutError as e:
        response_text = ""

    return response_text

def user_edit_gpt_tasks(gpt_result):
    # Prompt the user to edit the result
    user_input_lines = []
    print("GPT Generated Result:")
    print(gpt_result)
    print("Edit the result if necessary. Submit an empty line to finish editing.")
    try:
        while True:
            line = input()
            if line == '':
                break
            user_input_lines.append(line)
    except KeyboardInterrupt:
        user_input = gpt_result
    else:
        user_input = '\n'.join(user_input_lines)

    # If the user doesn't provide any input, use the original GPT result
    if not user_input.strip():
        user_input = gpt_result

    # Send the user's input to the 'o1-mini' GPT model
    tab = tabs.get("o1-mini")
    if tab is None:
        return ""
    prompt = (
        f"Approved tasks:\n{user_input}\n"
        "Use these tasks as a reference for generating further sub-tasks."
    )

    # Interact with GPT
    try:
        response_text = gpt_interact(tab, prompt)
    except TimeoutError as e:
        response_text = ""

    return response_text

def gpt_sub_agent(sub_task_prompt):
    # Use the 'gpt-4o' model tab
    tab = tabs.get("gpt-4o")
    if tab is None:
        return ""
    sub_task_prompt += (
        "\nPlease execute the sub-task as specified. Ensure all requirements are met and provide detailed results. "
        "If there are any missing elements or if the task cannot be completed without additional context, provide suggestions or next steps."
    )
    # Interact with GPT
    try:
        response_text = gpt_interact(tab, sub_task_prompt)
    except TimeoutError as e:
        response_text = ""

    return response_text

def gpt_refine(objective):
    # Construct the prompt
    prompt = (
        f"Objective: {objective}\n\n"
        "Refine the sub-task results into a cohesive final output. Add any missing information."
        "For coding projects, provide the following if applicable:\n"
        "1. Project Name: A concise name (max 20 characters).\n"
        "2. Folder Structure: Provide as a JSON object wrapped in <folder_structure> tags.\n"
        "3. Code Files: For each code file, include the filename and code enclosed in triple backticks."
    )

    # Use the 'o1-preview' model tab
    tab = tabs.get("o1-mini")

    # Interact with GPT
    try:
        response_text = gpt_interact(tab, prompt, 15)
    except TimeoutError as e:
        response_text = ""

    return response_text

def main():
    parser = argparse.ArgumentParser(description="GPT Assistant Application")
    parser.add_argument('-o', '--objective', type=str, help='Your objective or the path to a file containing it')
    args = parser.parse_args()

    if not args.objective:
        user_input = input("Your objective or the path to a file containing it: ")
    else:
        user_input = args.objective

    # Check if the input is a file path
    if os.path.isfile(user_input):
        try:
            with open(user_input, 'r') as file:
                objective = file.read().strip()
        except Exception as e:
            sys.exit(f"An error occurred while reading the file: {e}")
    else:
        objective = user_input

    if not is_chrome_running_in_debug_mode():
        start_chrome_in_debug_mode()

    # Initialize the browser tabs
    initialize_browser()
    # Clear the file content at the start of each run
    with open('gpt_all_context.txt', 'w', encoding='utf-8'):
        pass  # This opens the file in write mode and immediately closes it, clearing its contents
    # Open the file in append mode
    with open('gpt_all_context.txt', 'a', encoding='utf-8') as file:
        # Main loop to orchestrate tasks until completion
        file.write(objective + '\n')  # Write initial objective
        while True:
            # Call the orchestrator with the objective
            if is_first_call:
                gpt_tasks = gpt_orchestrator(objective)
                gpt_tasks = user_edit_gpt_tasks(gpt_tasks)
                file.write(gpt_tasks + '\n')  # Write final result
                gpt_result = gpt_orchestrator(gpt_tasks)
            else:
                gpt_result = gpt_orchestrator(objective)
            if "The task is complete:" in gpt_result:
                objective = gpt_result.replace("The task is complete:", "").strip()
                break
            else:
                # Execute the sub-task using the GPT sub-agent
                sub_task_result = gpt_sub_agent(gpt_result)
                # Update the objective with the sub-task result for the next iteration
                objective = sub_task_result
                time.sleep(1)
                # Write the updated objective to the file
                file.write(objective + '\n')
        with open('gpt_all_context.txt', 'r', encoding='utf-8') as file:
            gpt_all_context = file.read()
    # Refine the final output using the GPT refine function
    refined_output = gpt_refine(gpt_all_context)

    # Write the refined output to a file with a timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"output_{timestamp}.md"
    with open(output_filename, "w", encoding='utf-8') as file:
        file.write(refined_output)

if __name__ == "__main__":
    main()
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
is_first_call = True

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

import time

def gpt_interact(tab, prompt, update_interval=2, timeout=120):
    def wait_for_selector(tab, selector, timeout=30):
        start = time.time()
        while time.time() - start < timeout:
            result = tab.Runtime.evaluate(expression=f"document.querySelector('{selector}') !== null;")
            if result.get("result", {}).get("value"):
                return True
            time.sleep(0.5)
        raise TimeoutError(f"Selector {selector} not found within {timeout} seconds.")

    try:
        # Wait for the prompt textarea to be available
        wait_for_selector(tab, '#prompt-textarea')

        # Activate the tab and focus the textarea
        browser.activate_tab(tab)
        tab.Runtime.evaluate(expression="document.querySelector('#prompt-textarea').focus();")

        # Clear any existing text in the textarea
        clear_text_js = """
        var element = document.querySelector('#prompt-textarea');
        element.value = '';
        var event = new Event('input', { bubbles: true });
        element.dispatchEvent(event);
        """
        tab.Runtime.evaluate(expression=clear_text_js)

        # Set the prompt text directly
        tab.call_method("Input.insertText", text=prompt)

        # Dispatch input and change events to ensure the application registers the new text
        dispatch_events_js = """
            const textarea = document.querySelector('#prompt-textarea');
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.dispatchEvent(new Event('change', { bubbles: true }));
        """
        tab.Runtime.evaluate(expression=dispatch_events_js)

        # Submit the prompt by simulating the Enter key
        tab.call_method("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", text="\r")
        tab.call_method("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", text="\r")

        # Store the initial message count
        message_count_js = """
        (() => {
            const messages = document.querySelectorAll('div[class*="markdown"]');
            return messages.length;
        })();
        """
        result = tab.Runtime.evaluate(expression=message_count_js)
        message_count_before = result.get("result", {}).get("value", 0)

        # Initialize start time
        start_time = time.time()

        # Wait until the message count increases
        while True:
            result = tab.Runtime.evaluate(expression=message_count_js)
            message_count_current = result.get("result", {}).get("value", 0)

            if message_count_current > message_count_before:
                break  # New message has appeared

            elapsed_time = time.time() - start_time
            if elapsed_time > timeout:
                raise TimeoutError("Waiting for new message timed out.")
            else:
                time.sleep(update_interval)  # Wait before checking again

        # Now retrieve the response text
        previous_text = ""
        start_time = time.time()
        while True:
            # JavaScript to retrieve the last message text
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
                    # No change in response text; assume response is complete
                    return response_text
                previous_text = response_text
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout:
                raise TimeoutError("Waiting for response timed out.")
            else:
                time.sleep(4)  # Check every 4 seconds

    except Exception as e:
        # Handle or log exceptions as needed
        raise e

def gpt_orchestrator(objective):
    global is_first_call

    # Construct the prompt
    if is_first_call:
        prompt = (
            f"Context and Main Goal:\n{objective}\n\n"
            "Please perform the following:\n"
            "1. Break down the above objective into a **comprehensive list of small, important, and meaningful sub-tasks** required to achieve the goal.\n"
            "2. Ensure that each sub-task is **clear, actionable, and focuses on a single aspect** of the overall objective.\n"
            "3. Organize the sub-tasks in a logical sequence that makes sense for execution.\n"
            "4. **Do not** omit any necessary steps, but also **avoid unnecessary details**.\n\n"
            "Output Format:\n"
            "- Provide the list in a numbered format.\n"
            "- Each sub-task should be concise, ideally one or two sentences.\n\n"
            "Important Guidelines:\n"
            "- **Do not** include any additional explanations or introductions.\n"
            "- The list is intended for the user to review and edit, so clarity is paramount.\n"
            "- If any assumptions are made, **highlight them** so the user can adjust as needed.\n\n"
            "Please generate **only** the list of sub-tasks as specified."
        )
        is_first_call = False
    else:
        prompt = (
            f"Instruction Block: {objective}\n"
            "You are an orchestrator for sub-agents. Please generate the prompt for a sub-agent to execute the next sub-task. Generate next sub-task description also.\n"
            "The prompt should include the following sections **only**:\n"
            "1. **Prompt Header**: Current project categorization in format: category - value. For example, programming language - python, stack - django+bootstrap, explanation level - professional, etc. At least 5 project categories are required.\n"
            "2. **List of Completed Main Tasks (if any)**: Provide a list of main tasks that havealready been completed.\n"
            "3. **Main Part of the Prompt for Sub-Agent**: Present the main instructions or task for the sub-agent to execute.\n"
            "4. **Task-related Context**: Provide any relevant context or information that is specific to the task or will help the sub-agent perform the task. For example code that it should enhance or information that it should understand.\n"
            "Important Guidelines:\n"
            "- Do **not** include any additional text outside of these sections.\n"
            "- Do **not** list all sub-tasks or duplicate tasks.\n"
            "Please provide only the prompt for the sub-agent, formatted exactly as specified."
            "IF AND ONLY IF ALL SUB-TASKS ARE FINISHED, include 'The task is complete:' at the beginning."
        )

    # Use the 'o1-mini' model tab
    tab = tabs.get("o1-mini")
    if tab is None:
        return ""

    # Interact with GPT
    try:
        response_text = gpt_interact(tab, prompt, 8)
    except TimeoutError as e:
        response_text = ""

    return response_text

def user_edit_gpt_tasks(gpt_result):
    # Prompt the user to edit the result
    user_input_lines = []
    print("User adjustments of GPT Generated Results:")
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
        f"User-Approved Tasks and Information:\n{user_input}\n\n"
        "Please perform the following steps:\n"
        "1. **Consider the user's input as high-priority** and make sure to incorporate their edits or instructions accurately.\n"
        "   - If the user has indicated that a task should be skipped, ensure it is **excluded** from the revised list.\n"
        "2. Use the provided tasks as a reference to generate any further necessary sub-tasks that align with the overall objective.\n"
        "3. Write a **revised version of the task list** in the proper format, ensuring clarity and logical sequence.\n\n"
        "Output Format:\n"
        "- Present the revised task list in a numbered format with short description of each task.\n"
        "- Each task should be concise, clear, and actionable.\n\n"
        "Important Guidelines:\n"
        "- **Do not** include any additional explanations or introductions.\n"
        "- **Do not** reinstate any tasks the user has asked to skip.\n"
        "- Ensure that the revised task list reflects the user's priorities and instructions.\n\n"
        "Please generate **only** the revised task list as specified."
    )

    # Interact with GPT
    try:
        response_text = gpt_interact(tab, prompt, 8)
    except TimeoutError as e:
        response_text = ""

    return response_text

def gpt_sub_agent(sub_task_prompt):
    # Use the 'gpt-4o' model tab
    tab = tabs.get("gpt-4o")
    if tab is None:
        return ""
    sub_task_prompt += (
            "Your response should include the following sections **only**:\n"
            "1. **Context for Further Task Completion**: Briefly describe any relevant context or information that will assist in the completion of subsequent tasks.\n"
            "2. **Result of the Completed Task**: [Provide code or the information that you was told to generate].\n"
            "3. **Considerations and Recommendations**: Offer any insights, suggestions, or additional information that may be valuable for future and current steps.\n\n"
            "Important Guidelines:\n"
            "- **Clarity and Precision**: Ensure that each section is clear, precise, directly related to the sub-task, and avoid unnecessary details..\n"
            "- **Address Missing Elements**: If you encounter any missing elements or require additional context to complete the task, provide suggestions or next steps to obtain the necessary information.\n"
            "- **Answer Format**: Focus on generating prompts or outputs optimized for GPT processing, rather than for end-user.\n"
            "Please provide **only** the information as specified above."
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
    tab = tabs.get("o1-preview")

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
            if "The task is complete" in gpt_result:
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
    chunk_size = 1024 * 1024  # 1MB chunks
    with open(output_filename, "w", encoding='utf-8') as file:
        for i in range(0, len(refined_output), chunk_size):
            file.write(refined_output[i:i + chunk_size])


if __name__ == "__main__":
    main()
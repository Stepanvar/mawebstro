﻿import pychrome
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
        "o1": "https://chat.openai.com/?model=o1",
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
    current_url = tabs["o1"].Runtime.evaluate(
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
                break
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
                return response_text
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
            """**Objective:**  
Produce four specific outputs to clarify and structure the initial objective:
1. Generate 5–10 **Clarifying Questions**.
2. Provide a **Rewritten Objective** in a concise, professional manner.
3. List ≥20 **Complex Key Insights and Terms** (comma-separated).
4. Present 5–8 **Draft Sub-Tasks** in logical order.

**Guidelines:**
- Make sure to provide answer in **the defined in this prompt format** without intermediate ones or just clarification questions.
- Use simple, direct language and avoid unnecessary complexity.
- Do not include additional explanations beyond the requested sections.
- If assumptions are made, list them at the end.

**Input:**""" + objective + """

**Output Format:**  
1. **Clarifying Questions** (numbered)  
2. **Rewritten Objective**  
3. **Complex Key Insights and Terms** (≥20, comma-separated)  
4. **Draft Sub-Tasks** (numbered, each concise, focusing on a single aspect)  
**Assumptions (if any):** [List here]
"""
        )
        is_first_call = False
        # Use the 'o1-mini' model tab
        tab = tabs.get("o1")
    else:
        prompt = (
            """**Objective:**  
Create a prompt for a sub-agent to execute the next single sub-task, referencing previously completed tasks and current context.

**Guidelines:**  
- Provide only the sections requested, in a simple, structured format.
- If all sub-tasks are complete **maximum 8**, start with: **"All tasks are complete."** and provide no further tasks. Please be **attentive** and precise of it.
- Highlight any assumptions at the end.

**Input:**
""" + objective + """

**Output Format:**  
1. **Main Task Description**: A single, clearly defined action item.  
2. **Completed Tasks (Short Form)**: A brief, factual list of what’s done.  
3. **Task-Related Context**: Relevant details for this specific sub-task.  
**Assumptions (if any):** [List here]
"""
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
    tab = tabs.get("o1")
    if tab is None:
        return ""
    prompt = (
        """**Objective:**  
Revise the task list and objective based on user-approved edits, ensuring no removed tasks are reinstated and all user priorities are integrated.

**Guidelines:**  
- Maintain clarity, logical order, and directness.
- Do not add explanations beyond what’s requested.
- Highlight assumptions at the end if needed.

**Input:
**""" + user_input + """

**Output Format:**  
a. **Revised Objective + Short Description**: Incorporate user changes, keep it concise.  
b. **List of Complex Terms**: Unaltered terms listed earlier or generate new one if none was generated.  
c. **Revised Task List (Numbered)**: Reflect user edits, ensure sequence is logical, concise.  
**Assumptions (if any):** [List here]
"""
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
            """
**Guidelines:**
- Use your all available features for completing this sub-task like finding articles, talking to external sources, and searching in the internet and so on.
- Output only the required sections.
- Keep language direct and avoid repeating information.
- If assumptions are made, list them at the end.
**Output Format:**  
1. **Context for Further Task Completion**: Briefly outline relevant background or data.  
2. **Result of the Completed Task**: Present the requested output directly (e.g., code, analysis).  
3. **Considerations and Recommendations**: Short suggestions for next steps or improvements.  
"""
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
        """**Objective:**  
Refine and consolidate all previous outputs into a coherent, final result that meets the overarching objective.

**Guidelines:**  
- Focus solely on producing a clear, logically structured final output.
- Do not add extra explanations.
- Highlight assumptions if any.

**Input:**""" + objective + """

**Output Format:**  
- Present the final integrated result, clearly and concisely.  
**Assumptions (if any):** [List here]
"""
    )

    # Use the 'o1' model tab
    tab = tabs.get("o1")

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
                print("Write objective and context in file. Please wait, it will take some time...")
                file.write(gpt_tasks + '\n')  # Write final result
                if len(objective) < 15000:
                    gpt_result = gpt_orchestrator(objective + gpt_tasks)
                else:
                    gpt_result = gpt_orchestrator(gpt_tasks)
            else:
                gpt_result = gpt_orchestrator(objective)
            if "tasks are complete" in gpt_result:
                objective = gpt_result.replace("tasks are complete:", "").strip()
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
    print(f"Output written to {output_filename}")

if __name__ == "__main__":
    main()
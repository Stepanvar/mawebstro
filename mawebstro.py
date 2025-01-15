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
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import re


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
        "o1": "https://chat.openai.com/?model=gpt-4o",
        "o1-mini": "https://chat.openai.com/?model=gpt-4o",
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
            """### Goal:
Understand the user's main task and identify missing details, preferred methods, technologies, and a preliminary breakdown of subtasks.

### Instructions:
1. Analyze the provided description of the task.
2. Generate 5-10 clarifying questions in different fields aimed at:
   - Missing information about the task's context.
   - User preferences for methods, technologies, and specific requirements not mentioned.
3. Provide preliminary short options for the clarifying questions where possible.
4. Propose a preliminary list of subtasks based on the understanding of the main task.

### Constraints and Assumptions:
- **Constraints:**
  1. Avoid making assumptions about user preferences without clarification.
  2. Avoid using similar questions or tasks.
- **Assumptions:**
  1. The user seeks a detailed understanding of their task.
  2. The generated subtasks are a draft and may need refinement.

### Output Format:
- **Clarifying Questions:** A list of 5-10 clarifying questions. For each question, provide a potential answer or suggest options if relevant.
- **Preliminary Subtasks:** A numbered list of subtasks based on the task description.
- **Key Insights:**
  1. [Summarize any critical information or patterns from the user's input.]
  2. [Highlight connections between various aspects of the task.]
  3. [Mention any gaps or ambiguities in the provided information.]
  """ + "\n ### Input:" + "\n" + objective
        )
        is_first_call = False
        # Use the 'o1-mini' model tab
        tab = tabs.get("o1-mini")
    else:
        prompt = (
            """### Goal:
You are an intelligent orchestrator managing GPT models designed for education and code generation. Generate a clear and specific prompt for executing a subtask, incorporating all relevant context.

### Instructions:
1. Identify the next subtask from the provided list.
2. Extract only the context necessary for this subtask and ensure it provides all required details for execution.
3. Define the required output format for the subtask.
4. If all sub-tasks are complete **maximum 10**, start with: **"All tasks are complete."** and provide no further tasks. Please be **attentive** and precise of it.

### Constraints and Assumptions:
- **Constraints:**
  1. Focus only on the current subtask.
  2. Avoid duplicating information in the sub-tasks's context.
  3. 
- **Assumptions:**
  1. The subtask will contribute to the main task's completion.

### Output Format:
- Clear subtask description. Begin the subtask description with phrase: "You are a sub agent of most advanced Neuro orchestra. You must complete this sub-task:".
- Context and requirements for the subtask. Provide insights into the user's preferences and objectives. If you ask sub-ahent to adjust the text or code, **make sure** that you **provide** this text or code here.

""" + "### Input:" + "\n" + objective
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
        """### Goal:
Create a structured and professional description of the task and its context, ensuring missing information is addressed and tasks are logically refined.

### Instructions:
1. Identify and prioritize any missing critical information necessary for task completion before rewriting the task description.
2. Rewrite the task description in a concise and professional format.
3. Define the main goal and a logical list of subtasks, ensuring:
   - Extremely professional terminology is used.
   - Tasks are actionable and organized in a logical sequence.
   - Considering provided user input information IN PRIORITY. USE IT AS REFERENCE AND CONTEXT.

### Constraints and Assumptions:
- **Constraints:**
  1. Do not omit any critical details provided by the user.
  2. **Maximum** amount of **10** subtasks in list(in 10 subtasks, use 2 default first ones: to address missing information, refining existing subtasks based on received information).
- **Assumptions:**
  1. The rewritten version will guide further steps and sub-agents.

### User input:
""" + user_input + """


### Output Format:
- **Main Task Description:** A concise and professional task description.
- **Subtasks:** A numbered list of subtasks.
- **Key Assumptions:** A brief summary of assumptions based on the current context.
- **Key Insights:**
  1. [Summarize any critical patterns or themes in the user’s input.]
  2. [Highlight the most significant gaps in the provided details.]
  3. [Note any specific connections between subtasks and the main goal.]

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
    sub_task_prompt = (
            """
### Instructions:
1. Use the provided context to perform the subtask and **all** available features for completing this sub-task like **finding articles**, **talking to external sources**, **searching in the internet**, and so on.
2. If the context is insufficient, propose 2 simple, alternative solutions that align with the overarching goal.
4. Review the results to ensure they meet the requirements and are free of significant errors.
 

### Constraints and Assumptions:
- **Constraints:**
  1. Do not introduce drastic changes to the MAIN task's approach.
  2. DO NOT DESCRIBE WHAT YOU SHOULD DO. JUST DO IT.
- **Assumptions:**
  1. Medium variations in implementation are acceptable.

### Output Format:
- [Completed BY YOU task **result or multiple solutions**(parts of text, code blocks, or both).]
- Report any new information or insights gained during the task execution.
""" + "\n" + sub_task_prompt
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
        """### Goal:
Analyze and finalize the results of all subtasks into a complete and cohesive solution for the main task.

### Instructions:
1. Consolidate outputs from all subtasks into a cohesive result(fully completed text or code), ensuring logical flow and alignment with the main task.
2. Fill in any missing elements based on the task's context or assumptions where necessary.
3. Validate and correct any inconsistencies or errors in the intermediate results.
4. Ensure that the final solution fully addresses all aspects of the main task.

### Constraints and Assumptions:
- **Constraints:**
  1. Avoid introducing new subtasks or significant deviations from the original task.
  2. Maintain consistency with the user's goals and the provided context.

### Input:
""" + objective + """

### Output Format:
- **Final Result:** Provide a clear and concise solution that addresses the main task in full.
- **Corrections and Assumptions:** Include a section explaining any corrections, assumptions, or adjustments made during the consolidation process.

"""
    )

    # Use the 'o1' model tab
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
            with open(user_input, 'r', encoding='utf-8') as file:
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
        input("Configure tabs as you like and press enter to continue...")
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
    with open(output_filename, "w", encoding='utf-8') as file:
        file.write(refined_output)
    print(f"Output written to {output_filename}")

if __name__ == "__main__":
    main()
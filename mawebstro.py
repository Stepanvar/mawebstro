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
        "o1": "https://chatgpt.com/?model=gpt-4o",
        "o1-mini": "https://chatgpt.com/?model=gpt-4o",
        "gpt-4o": "https://chatgpt.com/?model=gpt-4o",
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

def get_unique_sentences(text, threshold=0.7):
    # Split text into sentences using regular expressions
    sentences = re.split(r'(?<=[.!?]) +', text)
    if not sentences or len(sentences) < 2:
        return "Not enough sentences to remove duplicates." + "\n" + text
    # Vectorize the sentences
    vectorizer = TfidfVectorizer().fit_transform(sentences)
    # Compute cosine similarity matrix
    cosine_sim = cosine_similarity(vectorizer)
    # Identify and remove similar sentences
    unique_sentences = []
    for idx, sentence in enumerate(sentences):
        if all(cosine_sim[idx][i] < threshold for i in range(idx)):
            unique_sentences.append(sentence)
    return ' '.join(unique_sentences)

def gpt_interact(tab, prompt, update_interval=2, timeout=120):
    def wait_for_selector(tab, selector, timeout=10):
        start = time.time()
        while time.time() - start < timeout:
            result = tab.Runtime.evaluate(expression=f"document.querySelector('{selector}') !== null;")
            if result.get("result", {}).get("value"):
                return True
            time.sleep(0.5)
        raise TimeoutError(f"Selector {selector} not found within {timeout} seconds.")

    def is_send_button_enabled(tab):
        # Check if the send button is not disabled
        check_button_js = """
        (() => {
            const testIds = ['send-button', 'composer-speech-button'];
            for (const id of testIds) {
                const btn = document.querySelector(`[data-testid="${id}"]`);
                if (btn && !btn.disabled) {
                    return true;
                }
            }
            return false;
        })();
        """
        result = tab.Runtime.evaluate(expression=check_button_js)
        return result.get("result", {}).get("value", False)

    def click_send_button(tab):
        click_js = """
        (() => {
            const btn = document.querySelector('[data-testid="send-button"]');
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        })();
        """
        result = tab.Runtime.evaluate(expression=click_js)
        return result.get("result", {}).get("value", False)

    # Retrieve the last response text from the DOM
    def get_last_response_text(tab):
        check_response_js = """
        (() => {
            const messages = document.querySelectorAll('div[class*="markdown"]');
            if (messages.length === 0) return null;
            const lastMessage = messages[messages.length - 1];
            return lastMessage ? lastMessage.textContent : null;
        })();
        """
        result = tab.Runtime.evaluate(expression=check_response_js)
        return result.get("result", {}).get("value", None)

    # Check if "Stop generating" or similar indicator is present
    def is_generating(tab):
        # Adjust selector or logic as needed if you have a known indicator:
        # For example, if a "Stop generating" button with testid='stop-button' appears:
        check_stop_js = """
        (() => {
            const stopBtn = document.querySelector('[data-testid="stop-button"]');
            return stopBtn !== null;
        })();
        """
        result = tab.Runtime.evaluate(expression=check_stop_js)
        return result.get("result", {}).get("value", False)

    try:
        # Wait for prompt textarea
        wait_for_selector(tab, '#prompt-textarea')

        # Focus the textarea
        browser.activate_tab(tab)
        tab.Runtime.evaluate(expression="document.querySelector('#prompt-textarea').focus();")

        # Clear existing text
        clear_text_js = """
        var element = document.querySelector('#prompt-textarea');
        element.value = "0"; //for send button not closed state 
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
        """
        tab.Runtime.evaluate(expression=clear_text_js)

        # Insert the prompt
        tab.call_method("Input.insertText", text=prompt)
        dispatch_events_js = """
            const textarea = document.querySelector('#prompt-textarea');
            textarea.dispatchEvent(new Event('input', { bubbles: true }));
            textarea.dispatchEvent(new Event('change', { bubbles: true }));
        """
        tab.Runtime.evaluate(expression=dispatch_events_js)

        # Wait for send button to be ready and enabled
        wait_for_selector(tab, '[data-testid="send-button"]')
        start_time = time.time()
        while not is_send_button_enabled(tab):
            if time.time() - start_time > timeout:
                raise TimeoutError("Send button not enabled within timeout.")
            time.sleep(0.5)

        # Click the send button
        if not click_send_button(tab):
            raise RuntimeError("Failed to click the send button.")

        # Now wait for the response
        # Wait until a new message appears
        initial_text = get_last_response_text(tab)
        start_time = time.time()

        # Wait for generation start: text changes or "stop" indicator
        while True:
            if time.time() - start_time > timeout:
                print("Timed out waiting for response.")
                break
            current_text = get_last_response_text(tab)
            if current_text and current_text != initial_text:
                # Response started to appear
                break
            time.sleep(update_interval)

        # Now wait for the response to stabilize
        # We'll wait until text no longer changes for a few consecutive checks
        stable_count = 0
        previous_text = get_last_response_text(tab)
        start_time = time.time()

        while True:
            time.sleep(2)
            current_text = get_last_response_text(tab)

            # If generating indicator is known (like a stop button), we can also rely on its disappearance
            # If none available, just rely on text stability
            if current_text == previous_text and current_text is not None:
                stable_count += 1
            else:
                stable_count = 0

            # Consider it stable if no change for a few consecutive checks
            if stable_count >= 3 and not is_generating(tab):
                # 3 checks with no change and no ongoing generation
                return current_text

            previous_text = current_text
            if time.time() - start_time > timeout:
                print("Timed out waiting for response to stabilize.")
                return current_text

    except Exception as e:
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
- **Preliminary Subtasks:** A **numbered** list of subtasks based on the task description.
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
1. Identify the next subtask from the **previously generated** list.
2. Extract only the context necessary for this subtask and ensure it provides all required details for execution.
3. Define the required output format for the subtask.
4. Find in all provided by user information and write block of text or code that will help sub-agent to understand the subtask.
5. IF AND ONLY IF all sub-tasks are complete **maximum 10** (minimum 4), write: **"All tasks are complete."** and provide no further tasks.

### Constraints and Assumptions:
- **Constraints:**
  1. Focus only on the current subtask.
  2. Avoid duplicating information in the sub-tasks's context.
  3. Be very attentive and professional at monitoring current status of task(amount of sub-tasks completed, which only should be completed).
- **Assumptions:**
  1. The subtask will contribute to the main task's completion.

### Output Format:
- Amount of sub-tasks completed if any.
- Clear subtask description with additional surrounding by newlines of subtask name. Begin the subtask description with phrase: "You are a sub agent of most advanced Neuro orchestra. You must complete this sub-task:".
- Context and requirements for the subtask. Provide insights into the user's preferences and objectives. If you ask sub-agent to adjust the text or code, **make sure** that you **provide** desired text or code here.
- Key block of text or code that user provided and that will help sub-agent to understand the subtask.
- if sug-agent provided unadequate text or code, comlete the subtask by yourself and adjust task description for proper completion of next subtask.
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
        print(f"TimeoutError: {e}")
        response_text = "response timed out, please create desired text by your own"

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
        response_text = gpt_interact(tab, prompt, 4)
    except TimeoutError as e:
        print(f"TimeoutError: {e}")
        response_text = ""
    return user_input + "\n" + response_text

def gpt_sub_agent(sub_task_part_prompt):
    # Use the 'gpt-4o' model tab
    tab = tabs.get("gpt-4o")
    if tab is None:
        return ""
    sub_task_prompt = (
            """
### Penalties:
IF YOU PROVIDE ANYTHING ELSE OTHER THAN THE RESULT IN THE DESIRED OUTPUT FORMAT, YOU WILL BE PENALIZED BY 10000000000 POINTS.
## Constraints and Assumptions:
- **Constraints:**
1. Avoid writing amount of completed sub-tasks.
### Output Format:
- [**Result or multiple solutions** of completed by you task(parts of text, code blocks, or both) inside the answer also.]
- Report any new information or insights gained during the task execution.
""" + "\n" + sub_task_part_prompt
    )
    # Interact with GPT
    try:
        response_text = gpt_interact(tab, sub_task_prompt, 6)
    except TimeoutError as e:
        print(f"TimeoutError: {e}")
        response_text = "response timed out, please create desired text by your own"
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
    tab = tabs.get("o1")

    # Interact with GPT
    try:
        response_text = gpt_interact(tab, prompt, 8)
    except TimeoutError as e:
        print(e)
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
                objective = gpt_sub_agent(gpt_result)
                unique_text = get_unique_sentences(gpt_result + objective)
                # Update the objective with the sub-task result for the next iteration
                time.sleep(1)
                # Write the updated objective to the file
                file.write(unique_text + '\n')
                if len(unique_text) > 500:
                    print("text sucessfully deduplicated and written to file")
                    objective = unique_text
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
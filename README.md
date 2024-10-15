# Mawebstro - A Framework for ChatGPT to Orchestrate Subagents via Web


This Python script demonstrates an AI-assisted task breakdown and execution workflow using the web interface of ChatGPT. It utilizes three AI models: o1-preview, o1-mini, and gpt4o to break down an objective into sub-tasks, execute each sub-task, and refine the results into a cohesive final output.

## Original project info
Same as in the https://github.com/Doriandarko/maestro

## Main information
1. It is used chatGPT web-interface so, history of tasks is saved and there is no need to repeat it in every prompt
2. It was created for personal and study use only, so don't use it in any inappropriate way or with commercial purposes
3. If you don't have paid version of ChatGPT, please change unavailable models to gpt4o
3. 
## Installation

1. Clone the repository or download the desired script file.
2. Install the required Python packages by running the following command:

```bash
pip install -r requirements.txt
```

3. Install, if neccessary and open Google Chrome via terminal(tested on Windows 10 and 11)

```bash
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:/Users/<User>/AppData/Local/Google/Chrome/User Data"
```

## Usage

1. Open a terminal or command prompt and navigate to the directory containing the script.
2. Run the script using the following command:

```bash
python maestro.py
```

3. Enter your objective when prompted:

```bash
Please enter your objective: Your objective here
```

The script will start the task breakdown and execution process. It will display the progress and results in the console using formatted panels.

Once the process is complete, the script will display the refined final output and save the full exchange log to a Markdown file with a filename based on the objective.

## Code Structure

The script consists of the following main functions:

- `gpt_orchestrator(objective, previous_results=None)`: Calls the ChatGPT model to break down the objective into sub-tasks or provide the final output. It uses an improved prompt to assess task completion and includes the phrase "The task is complete:" when the objective is fully achieved.
- `gpt_sub_agent(prompt, previous_haiku_tasks=None)`: Calls the Haiku model to execute a sub-task prompt, providing it with the memory of previous sub-tasks.
- `gpt_refine(objective, sub_task_results)`: Calls the ChatGPT model to review and refine the sub-task results into a cohesive final output.

The script follows an iterative process, repeatedly calling the gpt_orchestrator function to break down the objective into sub-tasks until the final output is provided. Each sub-task is then executed by the haiku_sub_agent function, and the results are stored in the task_exchanges and gpt_tasks lists.

The loop terminates when the ChatGPT model includes the phrase "The task is complete:" in its response, indicating that the objective has been fully achieved.

Finally, the gpt_refine function is called to review and refine the sub-task results into a final output. The entire exchange log, including the objective, task breakdown, and refined final output, is saved to a Markdown file.

## Customization

You can customize the script according to your needs

## License

This script is released under the MIT License.

## Acknowledgements
- OpenAI for providing the AI models and API.
- Rich for the beautiful console formatting.

## Keywords
- ChatGPT
- AI
- OpenAI
- Orchestration
- Web-API
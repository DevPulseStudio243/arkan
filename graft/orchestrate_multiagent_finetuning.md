# orchestrate_multiagent_finetuning.py

- log · function · L57-L62 — def log(msg)
- get_api · function · L65-L68 — def get_api()
- generate_agent_notebook · function · L71-L236 — def generate_agent_notebook(agent_name, dataset_file, kernel_slug)
- upload_agent_dataset_to_kaggle · function · L239-L282 — def upload_agent_dataset_to_kaggle(api)
- create_and_push_agent_kernel · function · L285-L324 — def create_and_push_agent_kernel(api, agent_name, kernel_slug, dataset_file, dataset_ref)
- check_all_kernels_status · function · L327-L338 — def check_all_kernels_status(api, agents_status)
- print_status_report · function · L341-L371 — def print_status_report(agents_status, start_time)
- main · function · L374-L451 — def main()

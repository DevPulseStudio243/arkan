# arkan_setup_launcher.py

- print_banner · function · L38-L49 — def print_banner()
- log_step · function · L52-L53 — def log_step(step_num: int, title: str, status: str = "EN COURS...")
- ensure_env_file · function · L56-L71 — def ensure_env_file()
- is_docker_running · function · L74-L80 — def is_docker_running() -> bool
- try_start_docker · function · L83-L100 — def try_start_docker()
- check_and_start_docker · function · L103-L128 — def check_and_start_docker()
- check_and_configure_ollama · function · L132-L182 — def check_and_configure_ollama()
- check_and_configure_nuextract · function · L185-L228 — def check_and_configure_nuextract()
- start_local_backend_if_needed · function · L232-L269 — def start_local_backend_if_needed(docker_started: bool)
- create_desktop_shortcut · function · L272-L301 — def create_desktop_shortcut()
- launch_browser · function · L304-L311 — def launch_browser()
- main · function · L314-L341 — def main()

# trainer_classifier.py

- ClassifierTrainer · class · L35-L369 — class ClassifierTrainer
- __init__ · method · L37-L41 — def __init__(self, data_dir: Path, models_dir: Path, console: Console)
- _load_data · method · L43-L62 — def _load_data(self) -> tuple
- _augment_with_real_docs · method · L64-L99 — def _augment_with_real_docs(self, texts: list, labels: list) -> tuple
- run · method · L101-L296 — def run(self)
- _patch_classifier · method · L298-L369 — def _patch_classifier(self, model_path: Path, classes: list)

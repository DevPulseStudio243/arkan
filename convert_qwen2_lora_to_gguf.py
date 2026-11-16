import json
import re
from pathlib import Path
import numpy as np
import gguf
from safetensors import safe_open

adapter_dir = Path(r"d:\DATA BASE IA\arkan_arh_lora_adapter")
config_path = adapter_dir / "adapter_config.json"
weights_path = adapter_dir / "adapter_model.safetensors"
output_gguf_path = adapter_dir / "adapter.gguf"

with open(config_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)

lora_alpha = float(cfg.get("lora_alpha", 16.0))
r_rank = int(cfg.get("r", 16))

print(f"Loading LoRA tensors from {weights_path}...")
writer = gguf.GGUFWriter(output_gguf_path, "qwen2")

writer.add_string("general.type", "adapter")
writer.add_string("general.architecture", "qwen2")
writer.add_string("adapter.type", "lora")
writer.add_float32("adapter.lora.alpha", lora_alpha)

name_map = {
    "self_attn.q_proj": "attn_q",
    "self_attn.k_proj": "attn_k",
    "self_attn.v_proj": "attn_v",
    "self_attn.o_proj": "attn_output",
    "mlp.gate_proj": "ffn_gate",
    "mlp.up_proj": "ffn_up",
    "mlp.down_proj": "ffn_down",
}

tensor_count = 0
with safe_open(weights_path, framework="pt") as f:
    for k in f.keys():
        t = f.get_tensor(k).numpy()
        # Pattern match: base_model.model.model.layers.X.MODULE.lora_A/B.weight
        m = re.search(r'layers\.(\d+)\.([a-z_\.]+)\.lora_([AB])\.weight', k)
        if m:
            layer_idx = m.group(1)
            module_hf = m.group(2)
            ab = m.group(3)
            
            gguf_module = name_map.get(module_hf)
            if not gguf_module:
                print(f"Warning: Unknown module {module_hf}")
                continue
            
            gguf_name = f"blk.{layer_idx}.{gguf_module}.weight.lora_{ab.lower()}"
            writer.add_tensor(gguf_name, t)
            tensor_count += 1
        else:
            print(f"Unmatched tensor key: {k}")

print(f"Writing {tensor_count} LoRA tensors to {output_gguf_path}...")
writer.write_header_to_file()
writer.write_kv_data_to_file()
writer.write_tensors_to_file()
writer.close()
print("Conversion to GGUF LoRA Adapter completed successfully!")

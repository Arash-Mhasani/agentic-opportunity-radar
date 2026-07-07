# Cross-domain transfer cues (reference)

A paper is a strong "adjacent_transfer" candidate when it ships a technique in one
field that maps onto a known robotics bottleneck:
- Vision/foundation models → perception, grasp affordance, sim-to-real appearance gap.
- Diffusion / flow matching → multimodal action generation, dexterous manipulation.
- Synthetic data / domain randomization → data scarcity for teleoperation.
- Efficient fine-tuning (LoRA-style) → on-robot adaptation without huge compute.
Set adjacent_transfer only when the mapping is specific and namable, not generic.

# routes/dots_router.py

- get_db · function · L17-L20 — def get_db()
- init_db · function · L22-L98 — def init_db()
- get_dots_status · function · L103-L117 — def get_dots_status()
- get_messages · function · L120-L124 — def get_messages()
- AnswerModel · class · L126-L127 — class AnswerModel(BaseModel)
- post_answer · function · L130-L153 — def post_answer(msg_id: int, payload: AnswerModel)
- get_logs · function · L156-L160 — def get_logs(since: float = 0.0)
- MissionModel · class · L162-L164 — class MissionModel(BaseModel)
- create_mission · function · L167-L175 — def create_mission(mission: MissionModel)
- get_training_status · function · L178-L182 — def get_training_status()

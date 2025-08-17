from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
import requests
import os

# ---------------- CONFIG ----------------
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
AQICN_API = os.getenv("AQICN_API")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
app = Flask(__name__)

# ---------------- ฟังก์ชัน ----------------
def get_aqi(city):
    url = f"https://api.waqi.info/feed/{city}/?token={AQICN_API}"
    r = requests.get(url).json()
    if r['status'] == 'ok':
        return r['data']['aqi']
    return None

def assess_risk(age, smoker, family_history, symptoms, aqi):
    score = 0
    if age < 12 or age > 60:
        score += 1
    if smoker:
        score += 2
    if family_history:
        score += 2
    score += len(symptoms)
    if aqi is not None and aqi > 100:
        score += 2

    if score <= 2:
        level = "ต่ำ"
        advice = "เดินทางได้ตามปกติ ดูแลสุขภาพทั่วไป"
    elif score <= 5:
        level = "ปานกลาง"
        advice = "ระวัง พกยา inhaler, ใส่หน้ากาก, หลีกเลี่ยงฝุ่น/ควัน"
    else:
        level = "สูง"
        advice = "ไม่ควรเดินทาง ควรปรึกษาแพทย์ก่อน"
    return level, advice

# ---------------- Webhook ----------------
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ---------------- Event Handler ----------------
user_data = {}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.lower()
    user_id = event.source.user_id

    # เริ่มต้น flow
    if text.startswith("ประเมิน"):
        user_data[user_id] = {"step": "age", "age": None, "smoker": None, "family": None, "symptoms": []}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาใส่อายุของคุณ (ตัวเลข):"))
        return

    data = user_data.get(user_id)
    if not data:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="พิมพ์ 'ประเมิน' เพื่อเริ่มประเมินอาการ"))
        return

    step = data["step"]

    # ---------------- Step: Age ----------------
    if step == "age":
        try:
            data["age"] = int(text)
            data["step"] = "smoker"
            qr = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="สูบบุหรี่", text="smoker:y")),
                QuickReplyButton(action=MessageAction(label="ไม่สูบบุหรี่", text="smoker:n"))
            ])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="คุณสูบบุหรี่หรือไม่?", quick_reply=qr))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาใส่ตัวเลขอายุ"))
        return

    # ---------------- Step: Smoker ----------------
    if step == "smoker" and text.startswith("smoker:"):
        data["smoker"] = text.split(":")[1] == "y"
        data["step"] = "family"
        qr = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="ครอบครัวมีประวัติหอบหืด", text="family:y")),
            QuickReplyButton(action=MessageAction(label="ไม่มีประวัติครอบครัว", text="family:n"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ประวัติครอบครัว?", quick_reply=qr))
        return

    # ---------------- Step: Family ----------------
    if step == "family" and text.startswith("family:"):
        data["family"] = text.split(":")[1] == "y"
        data["step"] = "symptoms"
        symptoms_qr = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="ไอ", text="อาการ:ไอ")),
            QuickReplyButton(action=MessageAction(label="จาม", text="อาการ:จาม")),
            QuickReplyButton(action=MessageAction(label="หายใจมีเสียงวี้ด", text="อาการ:หายใจมีเสียงวี้ด")),
            QuickReplyButton(action=MessageAction(label="แน่นหน้าอก", text="อาการ:แน่นหน้าอก")),
            QuickReplyButton(action=MessageAction(label="เหนื่อยง่าย", text="อาการ:เหนื่อยง่าย"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เลือกอาการของคุณ (สามารถเลือกหลายครั้ง):", quick_reply=symptoms_qr))
        return

    # ---------------- Step: Symptoms ----------------
    if step == "symptoms" and text.startswith("อาการ:"):
        symptom = text.replace("อาการ:","")
        if symptom not in data["symptoms"]:
            data["symptoms"].append(symptom)
        # หลังจากเลือกอาการแล้วไปเลือกเมือง
        data["step"] = "city"
        city_qr = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="กรุงเทพ", text="เมือง:กรุงเทพ")),
            QuickReplyButton(action=MessageAction(label="เชียงใหม่", text="เมือง:เชียงใหม่")),
            QuickReplyButton(action=MessageAction(label="ภูเก็ต", text="เมือง:ภูเก็ต")),
            QuickReplyButton(action=MessageAction(label="ขอนแก่น", text="เมือง:ขอนแก่น"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เลือกเมืองที่จะไป:", quick_reply=city_qr))
        return

    # ---------------- Step: City ----------------
    if step == "city" and text.startswith("เมือง:"):
        city = text.replace("เมือง:","")
        age = data["age"]
        smoker = data["smoker"]
        family_history = data["family"]
        symptoms = data["symptoms"]

        aqi = get_aqi(city)
        level, advice = assess_risk(age, smoker, family_history, symptoms, aqi)

        reply = f"""
📌 แบบประเมินความเสี่ยงโรคหอบหืด
อายุ: {age}, สูบบุหรี่: {smoker}, ครอบครัว: {family_history}
อาการ: {', '.join(symptoms)}

🌫 AQI: {aqi if aqi is not None else 'ไม่สามารถดึงค่าได้'}

⚠️ ระดับความเสี่ยง: {level}
💡 คำแนะนำ: {advice}
"""
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        # ปิด flow
        user_data[user_id]["step"] = "completed"
        return

    # ---------------- Completed / Other ----------------
    if step == "completed":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="คุณได้ทำการประเมินแล้ว หากต้องการประเมินใหม่ พิมพ์ 'ประเมิน'"))
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="พิมพ์ 'ประเมิน' เพื่อเริ่มประเมินอาการ"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

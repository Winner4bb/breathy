from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
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

# ---------------- QuickReply Templates ----------------
def get_smoker_qr():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="สูบบุหรี่", text="smoker:y")),
        QuickReplyButton(action=MessageAction(label="ไม่สูบบุหรี่", text="smoker:n"))
    ])

def get_family_qr():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="ครอบครัวมีประวัติหอบหืด", text="family:y")),
        QuickReplyButton(action=MessageAction(label="ไม่มีประวัติครอบครัว", text="family:n"))
    ])

def get_symptoms_qr():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="ไอ", text="อาการ:ไอ")),
        QuickReplyButton(action=MessageAction(label="จาม", text="อาการ:จาม")),
        QuickReplyButton(action=MessageAction(label="หายใจมีเสียงวี้ด", text="อาการ:หายใจมีเสียงวี้ด")),
        QuickReplyButton(action=MessageAction(label="แน่นหน้าอก", text="อาการ:แน่นหน้าอก")),
        QuickReplyButton(action=MessageAction(label="เหนื่อยง่าย", text="อาการ:เหนื่อยง่าย")),
        QuickReplyButton(action=MessageAction(label="ถัดไป", text="symptom:done"))
    ])

def get_city_qr():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="กรุงเทพ", text="เมือง:กรุงเทพ")),
        QuickReplyButton(action=MessageAction(label="เชียงใหม่", text="เมือง:เชียงใหม่")),
        QuickReplyButton(action=MessageAction(label="ภูเก็ต", text="เมือง:ภูเก็ต")),
        QuickReplyButton(action=MessageAction(label="ขอนแก่น", text="เมือง:ขอนแก่น"))
    ])

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
user_data = {}  # เก็บ session ผู้ใช้

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    # ---------------- RESET ----------------
    if text.lower() in ["รีเซ็ต", "reset"]:
        user_data.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔄 รีเซ็ตข้อมูลเรียบร้อยแล้ว\nพิมพ์ 'ประเมิน' เพื่อเริ่มใหม่")
        )
        return

    # ---------------- เริ่มต้น ----------------
    if text.startswith("ประเมิน"):
        user_data[user_id] = {
            "step": "age",
            "age": None,
            "smoker": None,
            "family": None,
            "symptoms": []
        }
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="กรุณาใส่อายุของคุณ (ตัวเลข):")
        )
        return

    # ---------------- STEP: AGE ----------------
    if user_data.get(user_id) and user_data[user_id]["step"] == "age":
        if text.isdigit():
            user_data[user_id]["age"] = int(text)
            user_data[user_id]["step"] = "smoker"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="คุณสูบบุหรี่หรือไม่?", quick_reply=get_smoker_qr())
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาใส่อายุเป็นตัวเลขอีกครั้ง")
            )
        return

    # ---------------- STEP: SMOKER ----------------
    if user_data.get(user_id) and user_data[user_id]["step"] == "smoker":
        if text in ["smoker:y", "smoker:n"]:
            user_data[user_id]["smoker"] = text.split(":")[1] == "y"
            user_data[user_id]["step"] = "family"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ครอบครัวของคุณมีประวัติหอบหืดหรือไม่?", quick_reply=get_family_qr())
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาเลือกจากตัวเลือกที่ให้ไว้ (สูบบุหรี่ / ไม่สูบ)", quick_reply=get_smoker_qr())
            )
        return

    # ---------------- STEP: FAMILY ----------------
    if user_data.get(user_id) and user_data[user_id]["step"] == "family":
        if text in ["family:y", "family:n"]:
            user_data[user_id]["family"] = text.split(":")[1] == "y"
            user_data[user_id]["step"] = "symptoms"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="เลือกอาการของคุณ (เลือกได้หลายครั้ง กด 'ถัดไป' เมื่อเสร็จ):", quick_reply=get_symptoms_qr())
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาเลือกจากตัวเลือกที่ให้ไว้ (มี / ไม่มี)", quick_reply=get_family_qr())
            )
        return

    # ---------------- STEP: SYMPTOMS ----------------
    if user_data.get(user_id) and user_data[user_id]["step"] == "symptoms":
        if text.startswith("อาการ:"):
            symptom = text.replace("อาการ:", "")
            if symptom not in user_data[user_id]["symptoms"]:
                user_data[user_id]["symptoms"].append(symptom)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"✅ เพิ่มอาการ: {symptom}\nเลือกอาการอื่นต่อ หรือกด 'ถัดไป' เมื่อเสร็จ:", quick_reply=get_symptoms_qr())
            )
        elif text == "symptom:done":
            user_data[user_id]["step"] = "city"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="เลือกเมืองที่จะไป:", quick_reply=get_city_qr())
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาเลือกอาการจากตัวเลือก หรือกด 'ถัดไป'", quick_reply=get_symptoms_qr())
            )
        return

    # ---------------- STEP: CITY ----------------
    if user_data.get(user_id) and user_data[user_id]["step"] == "city":
        if text.startswith("เมือง:"):
            city = text.replace("เมือง:", "")
            data = user_data[user_id]
            aqi = get_aqi(city)
            level, advice = assess_risk(data["age"], data["smoker"], data["family"], data["symptoms"], aqi)
            reply = f"""
📌 แบบประเมินความเสี่ยงโรคหอบหืด
อายุ: {data['age']}
สูบบุหรี่: {"ใช่" if data['smoker'] else "ไม่ใช่"}
ครอบครัว: {"มี" if data['family'] else "ไม่มี"}
อาการ: {', '.join(data['symptoms']) if data['symptoms'] else "ไม่มี"}

🌫 AQI ({city}): {aqi if aqi is not None else 'ไม่สามารถดึงค่าได้'}

⚠️ ระดับความเสี่ยง: {level}
💡 คำแนะนำ: {advice}
"""
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            user_data.pop(user_id, None)  # เคลียร์ session
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ กรุณาเลือกเมืองจากตัวเลือกที่ให้ไว้", quick_reply=get_city_qr()))
        return

    # ---------------- FALLBACK ----------------
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="พิมพ์ 'ประเมิน' เพื่อเริ่มทำแบบสอบถาม หรือ 'รีเซ็ต' เพื่อเริ่มใหม่")
    )

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

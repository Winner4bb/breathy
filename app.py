from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
import requests
import os
import unicodedata
import re

# ---------------- CONFIG ----------------
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
AQICN_API = os.getenv("AQICN_API")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
app = Flask(__name__)

# ---------------- ฟังก์ชัน ----------------
def get_aqi(city):
    """ดึงค่า AQI จาก API ตามชื่อเมือง"""
    url = f"https://api.waqi.info/feed/{city}/?token={AQICN_API}"
    try:
        r = requests.get(url).json()
        if r.get('status') == 'ok':
            return r['data']['aqi']
    except requests.exceptions.RequestException as e:
        print(f"Error fetching AQI: {e}")
    return None

def assess_risk(age, smoker, family_history, symptoms, aqi):
    """ประเมินความเสี่ยงและให้คำแนะนำตามข้อมูลที่ได้รับ"""
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

# ---------------- QuickReply ----------------
def get_smoker_qr():
    """สร้าง QuickReply สำหรับคำถามเรื่องการสูบบุหรี่"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="สูบบุหรี่", text="smoker:y")),
        QuickReplyButton(action=MessageAction(label="ไม่สูบบุหรี่", text="smoker:n"))
    ])

def get_family_qr():
    """สร้าง QuickReply สำหรับคำถามเรื่องประวัติครอบครัว"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="มี", text="family:y")),
        QuickReplyButton(action=MessageAction(label="ไม่มี", text="family:n"))
    ])

def get_symptoms_qr():
    """สร้าง QuickReply สำหรับคำถามเรื่องอาการ"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="ไอ", text="อาการ:ไอ")),
        QuickReplyButton(action=MessageAction(label="จาม", text="อาการ:จาม")),
        QuickReplyButton(action=MessageAction(label="หายใจมีเสียงวี้ด", text="อาการ:หายใจมีเสียงวี้ด")),
        QuickReplyButton(action=MessageAction(label="แน่นหน้าอก", text="อาการ:แน่นหน้าอก")),
        QuickReplyButton(action=MessageAction(label="เหนื่อยง่าย", text="อาการ:เหนื่อยง่าย")),
        QuickReplyButton(action=MessageAction(label="ถัดไป", text="symptom:done"))
    ])

def get_city_qr():
    """สร้าง QuickReply สำหรับคำถามเรื่องเมือง"""
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="กรุงเทพ", text="เมือง:กรุงเทพ")),
        QuickReplyButton(action=MessageAction(label="เชียงใหม่", text="เมือง:เชียงใหม่")),
        QuickReplyButton(action=MessageAction(label="ภูเก็ต", text="เมือง:ภูเก็ต")),
        QuickReplyButton(action=MessageAction(label="ขอนแก่น", text="เมือง:ขอนแก่น"))
    ])

# ---------------- Webhook ----------------
user_data = {}  # เก็บ session ผู้ใช้

@app.route("/callback", methods=['POST'])
def callback():
    """Handle Callback จาก Line API"""
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ---------------- Event Handler ----------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """Handle ข้อความที่ผู้ใช้ส่งมา"""
    raw_text = event.message.text
    text = unicodedata.normalize('NFC', raw_text).strip()
    user_id = event.source.user_id

    print(f"[DEBUG] user_id={user_id}, text={repr(text)}")

    # ---------------- RESET ----------------
    if re.search(r'\b(รีเซ็ต|reset)\b', text, re.IGNORECASE):
        user_data.pop(user_id, None)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔄 รีเซ็ตข้อมูลเรียบร้อยแล้ว\nพิมพ์ 'ประเมิน' เพื่อเริ่มใหม่")
        )
        return

    # ---------------- START ----------------
    if re.search(r'^\s*ประเมิน\s*$', text):
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

    # ---------------- PROCESS STEPS ----------------
    if user_id not in user_data:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="พิมพ์ 'ประเมิน' เพื่อเริ่มทำแบบสอบถาม หรือ 'รีเซ็ต' เพื่อเริ่มใหม่")
        )
        return
        
    step = user_data[user_id]["step"]

    # ----- STEP: AGE -----
    if step == "age":
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

    # ----- STEP: SMOKER -----
    if step == "smoker":
        if text == "smoker:y" or re.search(r'สูบ', text):
            user_data[user_id]["smoker"] = True
            user_data[user_id]["step"] = "family"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ครอบครัวของคุณมีประวัติหอบหืดหรือไม่?", quick_reply=get_family_qr())
            )
        elif text == "smoker:n" or re.search(r'ไม่\s*สูบ', text):
            user_data[user_id]["smoker"] = False
            user_data[user_id]["step"] = "family"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="ครอบครัวของคุณมีประวัติหอบหืดหรือไม่?", quick_reply=get_family_qr())
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาเลือกจากตัวเลือกที่ให้ไว้", quick_reply=get_smoker_qr())
            )
        return

    # ----- STEP: FAMILY -----
    if step == "family":
        if text == "family:y" or re.search(r'มี', text):
            user_data[user_id]["family"] = True
            user_data[user_id]["step"] = "symptoms"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="เลือกอาการของคุณ (เลือกได้หลายครั้ง กด 'ถัดไป' เมื่อเสร็จ):",
                    quick_reply=get_symptoms_qr()
                )
            )
        elif text == "family:n" or re.search(r'ไม่\s*มี', text):
            user_data[user_id]["family"] = False
            user_data[user_id]["step"] = "symptoms"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text="เลือกอาการของคุณ (เลือกได้หลายครั้ง กด 'ถัดไป' เมื่อเสร็จ):",
                    quick_reply=get_symptoms_qr()
                )
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาเลือกจากตัวเลือกที่ให้ไว้", quick_reply=get_family_qr())
            )
        return

    # ----- STEP: SYMPTOMS -----
    if step == "symptoms":
        if text.startswith("อาการ:"):
            symptom = text.replace("อาการ:", "").strip()
            if symptom and symptom not in user_data[user_id]["symptoms"]:
                user_data[user_id]["symptoms"].append(symptom)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=f"✅ เพิ่มอาการ: {symptom}\nเลือกอาการอื่นต่อ หรือกด 'ถัดไป' เมื่อเสร็จ:",
                    quick_reply=get_symptoms_qr()
                )
            )
        elif text == "symptom:done" or re.search(r'ถัดไป|เสร็จ', text):
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

    # ----- STEP: CITY -----
    if step == "city":
        city_mapping = {
            "เมือง:กรุงเทพ": "กรุงเทพ",
            "เมือง:เชียงใหม่": "เชียงใหม่",
            "เมือง:ภูเก็ต": "ภูเก็ต",
            "เมือง:ขอนแก่น": "ขอนแก่น"
        }
        
        city = None
        if text in city_mapping:
            city = city_mapping[text]
        elif re.search(r'กรุงเทพ|เชียงใหม่|ภูเก็ต|ขอนแก่น', text):
            city = text.replace("เมือง:", "").strip()

        if city:
            data = user_data.get(user_id)
            if not data:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="ข้อมูลของคุณหายไป กรุณาเริ่มใหม่ด้วยการพิมพ์ 'ประเมิน'")
                )
                return

            aqi = get_aqi(city)
            level, advice = assess_risk(data["age"], data["smoker"], data["family"], data["symptoms"], aqi)

            reply = f"""
📌 แบบประเมินความเสี่ยงโรคหอบหืด
อายุ: {data['age']}
สูบบุหรี่: {"ใช่" if data['smoker'] else "ไม่ใช่"}
ครอบครัว: {"มี" if data['family'] else "ไม่มี"}
อาการ: {', '.join(data['symptoms']) if data['symptoms'] else "ไม่มี"}

🌫 AQI ({city}): {aqi if aqi is not None else "ไม่สามารถดึงค่าได้"}

⚠️ ระดับความเสี่ยง: {level}
💡 คำแนะนำ: {advice}
"""
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            user_data.pop(user_id, None)  # เคลียร์ session หลังส่งผล
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="❌ กรุณาเลือกเมืองจากตัวเลือก", quick_reply=get_city_qr())
            )
        return
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
    try:
        r = requests.get(url).json()
        if r['status'] == 'ok':
            return r['data']['aqi']
    except:
        pass
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

# ---------------- Normalization Helper ----------------
def normalize_city(text):
    cities = {
        "กรุงเทพ": "เมือง:กรุงเทพ",
        "เมือง:กรุงเทพ": "เมือง:กรุงเทพ",
        "เชียงใหม่": "เมือง:เชียงใหม่",
        "เมือง:เชียงใหม่": "เมือง:เชียงใหม่",
        "ภูเก็ต": "เมือง:ภูเก็ต",
        "เมือง:ภูเก็ต": "เมือง:ภูเก็ต",
        "ขอนแก่น": "เมือง:ขอนแก่น",
        "เมือง:ขอนแก่น": "เมือง:ขอนแก่น"
    }
    return cities.get(text, None)

def normalize_symptom(text):
    symptoms = {
        "ไอ": "อาการ:ไอ",
        "อาการ:ไอ": "อาการ:ไอ",
        "จาม": "อาการ:จาม",
        "อาการ:จาม": "อาการ:จาม",
        "หายใจมีเสียงวี้ด": "อาการ:หายใจมีเสียงวี้ด",
        "อาการ:หายใจมีเสียงวี้ด": "อาการ:หายใจมีเสียงวี้ด",
        "แน่นหน้าอก": "อาการ:แน่นหน้าอก",
        "อาการ:แน่นหน้าอก": "อาการ:แน่นหน้าอก",
        "เหนื่อยง่าย": "อาการ:เหนื่อยง่าย",
        "อาการ:เหนื่อยง่าย": "อาการ:เหนื่อยง่าย"
    }
    return symptoms.get(text, None)

def normalize_family(text):
    if text in ["ไม่มีประวัติครอบครัว", "family:n"]:
        return "ไม่มีประวัติครอบครัว"
    if text in ["มีประวัติครอบครัว", "family:y"]:
        return "มีประวัติครอบครัว"
    return None

def normalize_smoker(text):
    if text in ["สูบบุหรี่", "smoker:y"]:
        return "สูบบุหรี่"
    if text in ["ไม่สูบบุหรี่", "smoker:n"]:
        return "ไม่สูบบุหรี่"
    return None

# ---------------- Webhook ----------------
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
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
    text = event.message.text.strip().lower()
    user_id = event.source.user_id

    qr_reset = QuickReply(items=[QuickReplyButton(action=MessageAction(label="รีเซ็ท", text="รีเซ็ท"))])

    if text == "รีเซ็ท":
        user_data[user_id] = None
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="ระบบถูกรีเซ็ทแล้ว\nพิมพ์ 'ประเมิน' เพื่อเริ่มใหม่"
        ))
        return

    if text.startswith("ประเมิน") or user_id not in user_data or user_data.get(user_id) is None:
        user_data[user_id] = {"step": "age", "age": None, "smoker": None, "family": None, "symptoms": []}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="กรุณาใส่อายุของคุณ (ตัวเลข):", quick_reply=qr_reset
        ))
        return

    data = user_data.get(user_id)
    if not data:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="พิมพ์ 'ประเมิน' เพื่อเริ่มประเมินอาการ", quick_reply=qr_reset))
        return

    step = data.get("step")

    # Step: age
    if step == "age":
        try:
            age = int(text)
            if age <= 0 or age > 120:
                raise ValueError
            data["age"] = age
            data["step"] = "smoker"
            qr_smoker = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="สูบบุหรี่", text="สูบบุหรี่")),
                QuickReplyButton(action=MessageAction(label="ไม่สูบบุหรี่", text="ไม่สูบบุหรี่")),
                QuickReplyButton(action=MessageAction(label="รีเซ็ท", text="รีเซ็ท"))
            ])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="คุณสูบบุหรี่หรือไม่?", quick_reply=qr_smoker))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาใส่ตัวเลขอายุที่ถูกต้อง", quick_reply=qr_reset))
        return

    # Step: smoker
    if step == "smoker":
        norm = normalize_smoker(text)
        if norm == "สูบบุหรี่":
            data["smoker"] = True
        elif norm == "ไม่สูบบุหรี่":
            data["smoker"] = False
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text="กรุณาเลือกจากตัวเลือก หรือพิมพ์ 'สูบบุหรี่', 'smoker:y', 'ไม่สูบบุหรี่', 'smoker:n'", quick_reply=qr_reset))
            return
        data["step"] = "family"
        qr_family = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="ครอบครัวมีประวัติหอบหืด", text="มีประวัติครอบครัว")),
            QuickReplyButton(action=MessageAction(label="ไม่มีประวัติครอบครัว", text="ไม่มีประวัติครอบครัว")),
            QuickReplyButton(action=MessageAction(label="รีเซ็ท", text="รีเซ็ท"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ครอบครัวมีประวัติหอบหืดหรือไม่?", quick_reply=qr_family))
        return

    # Step: family
    if step == "family":
        norm = normalize_family(text)
        if norm == "มีประวัติครอบครัว":
            data["family"] = True
        elif norm == "ไม่มีประวัติครอบครัว":
            data["family"] = False
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text="กรุณาเลือกจากตัวเลือก หรือพิมพ์ 'มีประวัติครอบครัว', 'family:y', 'ไม่มีประวัติครอบครัว', 'family:n'", quick_reply=qr_reset))
            return
        data["step"] = "symptom"
        symptoms_qr = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="ไอ", text="อาการ:ไอ")),
            QuickReplyButton(action=MessageAction(label="จาม", text="อาการ:จาม")),
            QuickReplyButton(action=MessageAction(label="หายใจมีเสียงวี้ด", text="อาการ:หายใจมีเสียงวี้ด")),
            QuickReplyButton(action=MessageAction(label="แน่นหน้าอก", text="อาการ:แน่นหน้าอก")),
            QuickReplyButton(action=MessageAction(label="เหนื่อยง่าย", text="อาการ:เหนื่อยง่าย")),
            QuickReplyButton(action=MessageAction(label="ถัดไป", text="ถัดไป")),
            QuickReplyButton(action=MessageAction(label="รีเซ็ท", text="รีเซ็ท"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="เลือกอาการของคุณ (เลือกได้หลายครั้ง กด 'ถัดไป' เมื่อเลือกเสร็จ):", quick_reply=symptoms_qr))
        return

    # Step: symptom
    if step == "symptom":
        norm = normalize_symptom(text)
        if norm:
            symptom = norm.replace("อาการ:", "")
            if symptom not in data["symptoms"]:
                data["symptoms"].append(symptom)
            symptoms_qr = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="ไอ", text="อาการ:ไอ")),
                QuickReplyButton(action=MessageAction(label="จาม", text="อาการ:จาม")),
                QuickReplyButton(action=MessageAction(label="หายใจมีเสียงวี้ด", text="อาการ:หายใจมีเสียงวี้ด")),
                QuickReplyButton(action=MessageAction(label="แน่นหน้าอก", text="อาการ:แน่นหน้าอก")),
                QuickReplyButton(action=MessageAction(label="เหนื่อยง่าย", text="อาการ:เหนื่อยง่าย")),
                QuickReplyButton(action=MessageAction(label="ถัดไป", text="ถัดไป")),
                QuickReplyButton(action=MessageAction(label="รีเซ็ท", text="รีเซ็ท"))
            ])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text="เลือกอาการเพิ่มเติม หรือกด 'ถัดไป' เมื่อเลือกเสร็จ:", quick_reply=symptoms_qr))
            return
        elif text == "ถัดไป":
            if not data["symptoms"]:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(
                    text="กรุณาเลือกอาการอย่างน้อย 1 อย่าง", quick_reply=qr_reset))
                return
            data["step"] = "city"
            city_qr = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="กรุงเทพ", text="เมือง:กรุงเทพ")),
                QuickReplyButton(action=MessageAction(label="เชียงใหม่", text="เมือง:เชียงใหม่")),
                QuickReplyButton(action=MessageAction(label="ภูเก็ต", text="เมือง:ภูเก็ต")),
                QuickReplyButton(action=MessageAction(label="ขอนแก่น", text="เมือง:ขอนแก่น")),
                QuickReplyButton(action=MessageAction(label="รีเซ็ท", text="รีเซ็ท"))
            ])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เลือกเมืองที่จะไป:", quick_reply=city_qr))
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาเลือกจากตัวเลือก หรือพิมพ์ชื่ออาการ เช่น 'ไอ', 'จาม', 'หายใจมีเสียงวี้ด', 'แน่นหน้าอก', 'เหนื่อยง่าย', หรือ 'ถัดไป'", quick_reply=qr_reset))
            return

    # Step: city
    if step == "city":
        norm = normalize_city(text)
        if norm:
            city = norm.replace("เมือง:", "")
            age = data["age"]
            smoker = data["smoker"]
            family_history = data["family"]
            symptoms = data["symptoms"]

            aqi = get_aqi(city)
            level, advice = assess_risk(age, smoker, family_history, symptoms, aqi)

            reply = f"""📌 แบบประเมินความเสี่ยงโรคหอบหืด
อายุ: {age}, สูบบุหรี่: {'สูบ' if smoker else 'ไม่สูบ'}, ครอบครัว: {'มี' if family_history else 'ไม่มี'}
อาการ: {', '.join(symptoms)}

🌫 AQI: {aqi if aqi is not None else 'ไม่สามารถดึงค่าได้'}

⚠️ ระดับความเสี่ยง: {level}
💡 คำแนะนำ: {advice}
"""
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply, quick_reply=qr_reset))
            user_data[user_id] = None  # ล้าง session
            return
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาเลือกจากตัวเลือก หรือพิมพ์ชื่อเมือง เช่น 'กรุงเทพ', 'เชียงใหม่', 'ภูเก็ต', 'ขอนแก่น'", quick_reply=qr_reset))
            return

    # ข้อความอื่น
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="พิมพ์ 'ประเมิน' เพื่อเริ่มประเมินอาการ", quick_reply=qr_reset))

# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

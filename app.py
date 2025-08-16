from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
import requests
import os

# ---------------- CONFIG ----------------
CHANNEL_ACCESS_TOKEN = os.getenv("Zv8W8x3YgffzXnnI95dJsfIvrU0on5agdFuQ/0OvK4Wf1KBLADD4MOD/FLlXPo3D5tAi6qwHLfOWaHeuTut9LrUuIxRhiBQqRp2EQbv9qUr9ilTXuHwNctYXH/ccpdSRzyu0Z6gJy6Y/Kz3Wg9SKXwdB04t89/1O/w1cDnyilFU=")
CHANNEL_SECRET = os.getenv("72873ed1e2c05e7ea560e617be24be08")
AQICN_API = os.getenv("96cff56bd643945ff35d0343b77ccb7419c3a820")

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

    if text.startswith("ประเมิน"):
        user_data[user_id] = {"symptoms":[], "age": None, "smoker": None, "family": None}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาใส่อายุของคุณ (ตัวเลข):"))
        return

    if user_data.get(user_id) and user_data[user_id]["age"] is None:
        try:
            user_data[user_id]["age"] = int(text)
            qr = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="สูบบุหรี่", text="smoker:y")),
                QuickReplyButton(action=MessageAction(label="ไม่สูบบุหรี่", text="smoker:n"))
            ])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="คุณสูบบุหรี่หรือไม่?", quick_reply=qr))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาใส่ตัวเลขอายุ"))
        return

    if user_data.get(user_id) and (text.startswith("smoker:") or text.startswith("family:")):
        if text.startswith("smoker:"):
            user_data[user_id]["smoker"] = text.split(":")[1] == "y"
            qr = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="ครอบครัวมีประวัติหอบหืด", text="family:y")),
                QuickReplyButton(action=MessageAction(label="ไม่มีประวัติครอบครัว", text="family:n"))
            ])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ประวัติครอบครัว?", quick_reply=qr))
        elif text.startswith("family:"):
            user_data[user_id]["family"] = text.split(":")[1] == "y"
            symptoms_qr = QuickReply(items=[
                QuickReplyButton(action=MessageAction(label="ไอ", text="อาการ:ไอ")),
                QuickReplyButton(action=MessageAction(label="จาม", text="อาการ:จาม")),
                QuickReplyButton(action=MessageAction(label="หายใจมีเสียงวี้ด", text="อาการ:หายใจมีเสียงวี้ด")),
                QuickReplyButton(action=MessageAction(label="แน่นหน้าอก", text="อาการ:แน่นหน้าอก")),
                QuickReplyButton(action=MessageAction(label="เหนื่อยง่าย", text="อาการ:เหนื่อยง่าย"))
            ])
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เลือกอาการของคุณ (สามารถเลือกหลายครั้ง):", quick_reply=symptoms_qr))
        return

    if text.startswith("อาการ:"):
        symptom = text.replace("อาการ:","")
        user_data[user_id]["symptoms"].append(symptom)
        city_qr = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="กรุงเทพ", text="เมือง:กรุงเทพ")),
            QuickReplyButton(action=MessageAction(label="เชียงใหม่", text="เมือง:เชียงใหม่")),
            QuickReplyButton(action=MessageAction(label="ภูเก็ต", text="เมือง:ภูเก็ต")),
            QuickReplyButton(action=MessageAction(label="ขอนแก่น", text="เมือง:ขอนแก่น"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เลือกเมืองที่จะไป:", quick_reply=city_qr))
        return

    if text.startswith("เมือง:"):
        city = text.replace("เมือง:","")
        data = user_data.get(user_id)
        if data:
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
            user_data[user_id] = {"symptoms":[], "age": None, "smoker": None, "family": None}
        return

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="พิมพ์ 'ประเมิน' เพื่อเริ่มประเมินอาการ"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

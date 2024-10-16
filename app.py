from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import logging
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import random
from openai import OpenAI
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
WORDS_COLLECTION_NAME = "words_collection"  # New words collection
EMAIL_COLLECTION_NAME = os.getenv("COLLECTION_NAME")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

app = FastAPI()

origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
emails_collection = db[EMAIL_COLLECTION_NAME]
words_collection = db[WORDS_COLLECTION_NAME]  # Collection for words

class Email(BaseModel):
    address: EmailStr

# Function to get words from MongoDB and update after use
def get_and_update_words():
    document = words_collection.find_one({})
    if document:
        words_dict = document["words"]
        words = list(words_dict.values())
        selected_words = random.sample(words, 2)
        for word in selected_words:
            words.remove(word)
        updated_words_dict = {str(i): word for i, word in enumerate(words)}
        words_collection.update_one({}, {"$set": {"words": updated_words_dict}})
        return selected_words
    else:
        raise HTTPException(status_code=500, detail="No words found in the database")

@app.get("/get-emails")
async def get_emails():
    try:
        emails = list(emails_collection.find({}, {"_id": 0}))
        return emails
    except ConnectionFailure:
        raise HTTPException(status_code=500, detail="Failed to connect to the database")

@app.post("/receive-email")
async def receive_email(email: Email):
    try:
        if emails_collection.find_one({"address": email.address}):
            return {"message": "Email already exists"}
        emails_collection.insert_one(email.dict())
        return {"message": "Email received and stored successfully"}
    except ConnectionFailure:
        raise HTTPException(status_code=500, detail="Failed to connect to the database")

@app.post("/unsubscribe")
async def unsubscribe(email: Email):
    try:
        result = emails_collection.delete_one({"address": email.address})
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Email not found")
        return {"message": "Email unsubscribed successfully"}
    except ConnectionFailure:
        raise HTTPException(status_code=500, detail="Failed to connect to the database")

@app.post("/send-emails")
async def send_emails():
    try:
        openai_client = OpenAI(api_key=OPENAI_API_KEY)
        
        # Fetch and update words from MongoDB
        selected_words = get_and_update_words()
        
        user_p = f"""
        [
            {{"word": "{selected_words[0]}", "definition": "", "example": ""}},
            {{"word": "{selected_words[1]}", "definition": "", "example": ""}}
        ]
        """
        sys_p = """
        You will be given two words. 
        You have to return this format in a json. 
        [{
            "word": "word1",
            "definition": "definition1",
            "example": "example1"
        },
        {
            "word": "word2",
            "definition": "definition2",
            "example": "example2"
        }]
        """
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys_p},
                {"role": "user", "content": user_p}
            ]
        )
        words_with_meanings = eval(response.choices[0].message.content.replace("```", "").replace("json", ""))
        html_template = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Daily Words</title>
            <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Roboto:wght@400;500&display=swap" rel="stylesheet">
            <style>
                body {{
                    margin: 0;
                    padding: 0;
                    font-family: 'Roboto', sans-serif;
                    background-color: #f3f4f6;
                    color: #333;
                }}

                .container {{
                    max-width: 600px;
                    margin: 50px auto;
                    padding: 20px;
                    background-color: white;
                    border-radius: 12px;
                    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
                }}

                h1 {{
                    font-family: 'Playfair Display', serif;
                    text-align: center;
                    font-size: 2.5em;
                    margin-bottom: 20px;
                    color: #3d5a80;
                }}

                .word-block {{
                    margin-bottom: 30px;
                }}

                .word {{
                    font-family: 'Playfair Display', serif;
                    font-size: 2em;
                    color: #1d3557;
                    margin: 10px 0;
                }}

                .definition {{
                    font-size: 1.2em;
                    margin: 10px 0;
                    color: #555;
                }}

                .example {{
                    font-size: 1em;
                    margin: 10px 0;
                    font-style: italic;
                    color: #888;
                }}

                .divider {{
                    height: 2px;
                    background-color: #d8e3e7;
                    margin: 40px 0;
                }}

                footer {{
                    text-align: center;
                    font-size: 0.9em;
                    color: #666;
                    margin-top: 30px;
                }}
            </style>
        </head>
        <body>

            <div class="container">
                <h1>Daily Words</h1>

                <div class="word-block">
                    <div class="word">1. {words_with_meanings[0]['word']}</div>
                    <div class="definition">{words_with_meanings[0]['definition']}</div>
                    <div class="example">Example: "{words_with_meanings[0]['example']}"</div>
                </div>

                <div class="divider"></div>

                <div class="word-block">
                    <div class="word">2. {words_with_meanings[1]['word']}</div>
                    <div class="definition">{words_with_meanings[1]['definition']}</div>
                    <div class="example">Example: "{words_with_meanings[1]['example']}"</div>
                </div>

                <footer>
                    Delivered to you with ❤️ by 2Words | Enhance your vocabulary daily | <a href="https://2words.vercel.com/unsubscribe">Unsubscribe</a>
                </footer>
            </div>

        </body>
        </html>
        """

        emails = list(emails_collection.find({}, {"_id": 0, "address": 1}))
        email = EMAIL_ADDRESS
        password = EMAIL_PASSWORD  # Be cautious when handling sensitive information like passwords

        subject = "Today's words ✨"

        for email_entry in emails:
            receiver_email = email_entry['address']

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = email
            msg["To"] = receiver_email
            part = MIMEText(html_template, "html")
            msg.attach(part)

            server = smtplib.SMTP("smtp.gmail.com", 587)
            server.starttls()
            server.login(email, password)
            server.sendmail(email, receiver_email, msg.as_string())
            server.quit()
            print(f"Email sent to {receiver_email}")

        return {"message": "Emails sent successfully"}
    except ConnectionFailure:
        raise HTTPException(status_code=500, detail="Failed to connect to the database")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(words_with_meanings))

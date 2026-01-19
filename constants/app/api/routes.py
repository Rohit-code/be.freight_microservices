from fastapi import APIRouter


router = APIRouter(prefix="/api/constants", tags=["constants"])


@router.get("/faqs")
def get_faqs():
    return {
        "faqs": [
            {
                "question": "Do I need technical knowledge to set up?",
                "answer": "Not at all! Our one-click Gmail integration gets you started in under 5 minutes. No coding or technical skills required.",
            },
            {
                "question": "How does the AI ensure accuracy?",
                "answer": "Our AI uses advanced machine learning models trained on millions of freight communications. We provide confidence scores for every response, and you can review any email before it's sent",
            },
            {
                "question": "What happens if the AI isn't confident?",
                "answer": "If confidence is below your threshold (default 95%), the email goes to your review queue instead of auto-sending. You maintain full control.",
            },
            {
                "question": "Can I review emails before they're sent?",
                "answer": "Absolutely! You can set your auto-send threshold, and any email below that confidence level will require your approval before sending.",
            },
            {
                "question": "Which carriers do you support?",
                "answer": "We integrate with major carriers including DHL, FedEx, Maersk, UPS, and many more. Custom integrations are available on Enterprise plans.",
            },
            {
                "question": "Is my data secure?",
                "answer": "Yes. We use bank-level 256-bit encryption, are SOC 2 compliant, and GDPR ready. Your data is stored securely and never shared.",
            },
        ]
    }

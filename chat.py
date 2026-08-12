import requests
import sys

URL = "http://localhost:8000/chat"
THREAD_ID = "user_test"

print("="*50)
print("Chat với Real Estate Agent (Gõ 'exit' hoặc 'quit' để thoát)")
print("="*50)

while True:
    try:
        user_input = input("\nBạn: ")
        if user_input.lower() in ["exit", "quit", "q"]:
            break
        if not user_input.strip():
            continue
            
        payload = {
            "message": user_input,
            "thread_id": THREAD_ID
        }
        
        response = requests.post(URL, json=payload)
        
        if response.status_code == 200:
            data = response.json()
            print(f"\nAgent: {data.get('text', '')}")
            
            # In ra các action (nút bấm) nếu có
            actions = data.get("actions", [])
            if actions:
                print("--- Gợi ý Hành động ---")
                for action in actions:
                    print(f"[{action.get('label')}] (type: {action.get('type')})")
        else:
            print(f"\n[Lỗi {response.status_code}] {response.text}")
            
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(f"\nLỗi kết nối: {e}")

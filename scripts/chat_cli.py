#!/usr/bin/env python3
"""Interactive Terminal Chatbot client for Customer Support RAG API."""

import json
import sys
import urllib.request

API_URL = "http://localhost:8000/api/chat"


def main() -> None:
    print("=" * 60)
    print(" 🤖 Customer Support RAG Chatbot")
    print(" (Type 'exit' or 'quit' to end session)")
    print("=" * 60)

    history: list[dict[str, str]] = []

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            payload = {
                "message": user_input,
                "history": history,
            }

            req = urllib.request.Request(
                API_URL,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )

            sys.stdout.write("Bot is searching knowledge base & thinking...\r")
            sys.stdout.flush()

            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            answer = data.get("answer", "")
            sources = data.get("sources", [])
            refused = data.get("refused", False)

            # Clear status line
            sys.stdout.write(" " * 60 + "\r")
            sys.stdout.flush()

            print(f"\nBot: {answer}")

            if sources and not refused:
                print("\n📚 Sources Cited:")
                seen = set()
                for s in sources:
                    doc_id = s.get("article_id") or s.get("ticket_id") or "N/A"
                    if doc_id not in seen:
                        seen.add(doc_id)
                        title = s.get("subject", "N/A")
                        print(f"   • [{doc_id}] {title}")

            # Keep conversation history for multi-turn chat memory
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": answer})

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            print("Make sure 'python run.py' is running in another terminal window!")


if __name__ == "__main__":
    main()

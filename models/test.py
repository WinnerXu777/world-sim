from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

# Start with a strong system prompt
messages = [{"role": "system", "content": "You are a concise AI Research Assistant. Answer Caleb's questions directly without repeating yourself."}]

print("\n--- Mixtral Fixed Agent (Anti-Loop Enabled) ---")

while True:
    user_input = input("\nCaleb: ")
    if user_input.lower() in ["exit", "quit"]: break
    
    messages.append({"role": "user", "content": user_input})

    try:
        response = client.chat.completions.create(
            model="TheBloke/Mixtral-8x7B-v0.1-AWQ",
            messages=messages,
            temperature=0.7,
            # THESE PREVENT THE LOOPING:
            presence_penalty=1.2,   # Penalizes the model for repeating topics
            frequency_penalty=0.5,  # Penalizes the model for repeating exact words
            max_tokens=1024,        # Prevents infinite generation
            stream=True
        )

        print("\nMixtral: ", end="", flush=True)
        answer = ""
        for chunk in response:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                print(content, end="", flush=True)
                answer += content
        print()
        
        messages.append({"role": "assistant", "content": answer})
        
        # MEMORY MANAGEMENT: Only keep the last 10 messages to avoid confusion
        if len(messages) > 11:
            messages = [messages[0]] + messages[-10:]

    except Exception as e:
        print(f"\nError: {e}")
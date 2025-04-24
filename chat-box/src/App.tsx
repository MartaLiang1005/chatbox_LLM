import React, { useState, useRef, useEffect } from "react";
import "./App.css";
import axios from "axios";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface ChatSession {
  id: number;
  title: string;
  messages: Message[];
}

const App: React.FC = () => {
  const [chats, setChats] = useState<ChatSession[]>([]);
  const [activeChatId, setActiveChatId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [sidebarWidth, setSidebarWidth] = useState(20); // Default to 20% width
  const sidebarRef = useRef<HTMLDivElement>(null);
  const isResizingRef = useRef(false);

  const createNewChat = () => {
    const newChat: ChatSession = {
      id: Date.now(),
      title: `Chat ${chats.length + 1}`,
      messages: [],
    };
    setChats((prev) => [...prev, newChat]);
    setActiveChatId(newChat.id);
    setInput("");        
  };

  const sendMessage = async () => {
    if (!input.trim() || activeChatId === null) return;

    // Build the new user message
    const userMsg: Message = { role: "user", content: input };

    // 1) Optimistically add user message to state
    setChats((prev) =>
      prev.map((chat) =>
        chat.id === activeChatId
          ? { ...chat, messages: [...chat.messages, userMsg] }
          : chat
      )
    );

    try {
      const { data } = await axios.post(`${BACKEND_URL}/chat`, {
        user_input: input,
        history: chats.find((c) => c.id === activeChatId)?.messages,
      });

      let botMsg: Message;

      if (data.clarify_person) {
        const optionsList = data.ambiguous_names
          .map((item: any) => `${item.name}: ${item.options.join(", ")}`)
          .join("\n");
        botMsg = {
          role: "assistant",
          content: `${data.message}\n${optionsList}`,
        };
      } else if (data.reframed_question && data.termination_status === false) {
        botMsg = {
          role: "assistant",
          content: `${data.reframed_question}\n${data.confirmation_message}`,
        };
      } else {
        botMsg = {
          role: "assistant",
          content: data.natural_response,
        };
      }

      // 3) Append bot response
      setChats((prev) =>
        prev.map((chat) =>
          chat.id === activeChatId
            ? { ...chat, messages: [...chat.messages, botMsg] }
            : chat
        )
      );
    } catch (err) {
      console.error(err);
      const errorMsg: Message = {
        role: "assistant",
        content: "Error fetching response.",
      };
      setChats((prev) =>
        prev.map((chat) =>
          chat.id === activeChatId
            ? { ...chat, messages: [...chat.messages, errorMsg] }
            : chat
        )
      );
    }

    setInput("");
  };

  /** Sidebar Resize Handlers **/
  const startResizing = () => {
    isResizingRef.current = true;
  };

  const stopResizing = () => {
    isResizingRef.current = false;
  };

  const resizeSidebar = (e: MouseEvent) => {
    if (!isResizingRef.current) return;
    const newWidth = (e.clientX / window.innerWidth) * 100;
    if (newWidth >= 10 && newWidth <= 40) {
      setSidebarWidth(newWidth);
    }
  };

  useEffect(() => {
    window.addEventListener("mousemove", resizeSidebar);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", resizeSidebar);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, []);

  const activeChat = chats.find((c) => c.id === activeChatId);

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div
        ref={sidebarRef}
        className="sidebar"
        style={{ width: `${sidebarWidth}%` }}
      >
        <h2>e-Discovery LLM</h2>
        <button className="new-chat-btn" onClick={createNewChat}>
          + New Chat
        </button>
        <ul>
          {chats.map((chat) => (
            <li
              key={chat.id}
              className={`history-item ${
                chat.id === activeChatId ? "active" : ""
              }`}
              onClick={() => {setActiveChatId(chat.id);  
                setInput("");}}
            >
              {chat.title}
            </li>
          ))}
        </ul>
        <div className="resizer" onMouseDown={startResizing} />
      </div>

      {/* Chat Window */}
      <div className="chat-container">
        {activeChat ? (
          <>
            <div className="chat-messages">
              {activeChat.messages.map((msg, idx) => (
                <div key={idx} className={`message ${msg.role}`}>
                  {msg.content}
                </div>
              ))}
            </div>
            <div className="input-container">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask a question..."
                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
              />
              <button onClick={sendMessage}>Send</button>
            </div>
          </>
        ) : (
          <div className="empty-chat">
            Start a new chat by clicking "+ New Chat"
          </div>
        )}
      </div>
    </div>
  );
};

export default App;

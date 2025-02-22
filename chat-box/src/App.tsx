import React, { useState, useRef } from "react";
import "./App.css";
import axios from "axios";

interface Message {
  role: "user" | "bot";
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
  };

  const sendMessage = async () => {
    if (!input.trim() || activeChatId === null) return;

    setChats((prevChats) =>
      prevChats.map((chat) =>
        chat.id === activeChatId
          ? {
              ...chat,
              messages: [...chat.messages, { role: "user", content: input }],
              title: chat.messages.length === 0 ? input : chat.title,
            }
          : chat
      )
    );

    try {
      const response = await axios.post("https://your-backend-api.com/chat", {
        message: input,
      });

      setChats((prevChats) =>
        prevChats.map((chat) =>
          chat.id === activeChatId
            ? { ...chat, messages: [...chat.messages, { role: "bot", content: response.data.reply }] }
            : chat
        )
      );
    } catch (error) {
      console.error("Error fetching response:", error);
      setChats((prevChats) =>
        prevChats.map((chat) =>
          chat.id === activeChatId
            ? { ...chat, messages: [...chat.messages, { role: "bot", content: "Error getting response." }] }
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

  React.useEffect(() => {
    window.addEventListener("mousemove", resizeSidebar);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", resizeSidebar);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, []);

  return (
    <div className="app-container">
      {/* Sidebar */}
      <div ref={sidebarRef} className="sidebar" style={{ width: `${sidebarWidth}%` }}>
        <h2>e-Discovery LLM</h2>
        <button className="new-chat-btn" onClick={createNewChat}>
          + New Chat
        </button>
        <ul>
          {chats.map((chat) => (
            <li
              key={chat.id}
              className={`history-item ${chat.id === activeChatId ? "active" : ""}`}
              onClick={() => setActiveChatId(chat.id)}
            >
              {chat.title}
            </li>
          ))}
        </ul>
        <div className="resizer" onMouseDown={startResizing} />
      </div>

      {/* Chat Window */}
      <div className="chat-container">
        {activeChatId !== null ? (
          <>
            <div className="chat-messages">
              {chats
                .find((chat) => chat.id === activeChatId)
                ?.messages.map((msg, index) => (
                  <div key={index} className={`message ${msg.role}`}>
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
          <div className="empty-chat">Start a new chat by clicking "+ New Chat"</div>
        )}
      </div>
    </div>
  );
};

export default App;

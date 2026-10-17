"""最常見的 LangGraph 聊天形狀（MessagesState）：用 app 目前選的模型回答。

在聊天裡打：/workflow example:chat 你的問題
"""
from langgraph.graph import END, START, MessagesState, StateGraph

import webui_app

llm = webui_app.get_chat_model()  # LangChain 的 chat model，走 app 的引擎


def respond(state: MessagesState) -> dict:
    return {"messages": [llm.invoke(state["messages"])]}


builder = StateGraph(MessagesState)
builder.add_node("respond", respond)
builder.add_edge(START, "respond")
builder.add_edge("respond", END)
graph = builder.compile()

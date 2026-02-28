# BrowseAI

An iOS browser app with a built-in AI chat agent. Browse the web with a full-featured WebKit browser and get instant help from a Gemini-powered assistant that can read and discuss the current page.

## Features

- **Full browser** — Address bar, back/forward/reload, swipe navigation via WKWebView
- **AI chat panel** — Slide-out chat sidebar powered by the Gemini API
- **Page-aware AI** — The agent can read and summarize the page you're currently viewing
- **iPhone & iPad** — Universal app with adaptive layout

## Project Structure

```
BrowseAI/
├── BrowseAIApp.swift          # App entry point
├── ContentView.swift          # Main split layout (browser + chat panel)
├── Info.plist
├── Views/
│   ├── BrowserView.swift      # WKWebView wrapper with toolbar
│   └── ChatView.swift         # Chat UI with message bubbles
├── Models/
│   ├── BrowserState.swift     # Browser navigation state
│   └── ChatState.swift        # Chat messages and state
└── Services/
    ├── GeminiService.swift    # Gemini API client
    └── WebViewCoordinator.swift  # WKWebView delegate
```

## Setup

1. Open `BrowseAI.xcodeproj` in Xcode 15+
2. Set your Gemini API key as an environment variable (`GEMINI_API_KEY`) in the scheme's Run configuration, or hardcode it in `GeminiService.swift`
3. Select a simulator or device and hit Run

## Requirements

- iOS 16.0+
- Xcode 15+
- A Gemini API key (get one at https://aistudio.google.com/apikey)

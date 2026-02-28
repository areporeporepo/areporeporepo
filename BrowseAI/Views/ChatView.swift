import SwiftUI

struct ChatView: View {
    @EnvironmentObject var chatState: ChatState
    @EnvironmentObject var browserState: BrowserState
    @State private var inputText: String = ""
    @FocusState private var isInputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            // Messages list
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        ForEach(chatState.messages) { message in
                            ChatBubbleView(message: message)
                                .id(message.id)
                        }

                        if chatState.isGenerating {
                            HStack {
                                TypingIndicator()
                                Spacer()
                            }
                            .padding(.horizontal)
                            .id("typing")
                        }
                    }
                    .padding(.vertical, 12)
                }
                .onChange(of: chatState.messages.count) { _ in
                    withAnimation {
                        if let last = chatState.messages.last {
                            proxy.scrollTo(last.id, anchor: .bottom)
                        }
                    }
                }
            }

            Divider()

            // Input bar
            inputBar
        }
    }

    private var inputBar: some View {
        HStack(spacing: 8) {
            // "Read page" shortcut
            Button {
                sendPageContext()
            } label: {
                Image(systemName: "doc.text.magnifyingglass")
                    .font(.body)
                    .foregroundColor(.blue)
            }
            .help("Send current page to AI")

            TextField("Ask the AI agent...", text: $inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...5)
                .focused($isInputFocused)
                .onSubmit {
                    sendMessage()
                }

            Button {
                sendMessage()
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundColor(inputText.trimmingCharacters(in: .whitespaces).isEmpty ? .gray : .blue)
            }
            .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty || chatState.isGenerating)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color(.secondarySystemBackground))
    }

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        inputText = ""
        chatState.addUserMessage(text)

        Task {
            await GeminiService.shared.sendMessage(
                text,
                pageContent: browserState.pageContent,
                pageURL: browserState.currentURL?.absoluteString,
                chatState: chatState
            )
        }
    }

    private func sendPageContext() {
        let pageURL = browserState.currentURL?.absoluteString ?? "unknown page"
        let prompt = "Summarize this page for me: \(pageURL)"
        inputText = ""
        chatState.addUserMessage(prompt)

        Task {
            await GeminiService.shared.sendMessage(
                prompt,
                pageContent: browserState.pageContent,
                pageURL: browserState.currentURL?.absoluteString,
                chatState: chatState
            )
        }
    }
}

// MARK: - Chat bubble

struct ChatBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 40) }

            VStack(alignment: message.role == .user ? .trailing : .leading, spacing: 4) {
                Text(message.content)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(bubbleColor)
                    .foregroundColor(message.role == .user ? .white : .primary)
                    .cornerRadius(18)

                Text(message.timestamp, style: .time)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }

            if message.role == .assistant { Spacer(minLength: 40) }
        }
        .padding(.horizontal, 12)
    }

    private var bubbleColor: Color {
        message.role == .user ? .blue : Color(.tertiarySystemBackground)
    }
}

// MARK: - Typing indicator

struct TypingIndicator: View {
    @State private var dotCount = 0
    let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<3) { index in
                Circle()
                    .fill(Color.secondary)
                    .frame(width: 8, height: 8)
                    .opacity(dotCount % 3 == index ? 1.0 : 0.3)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color(.tertiarySystemBackground))
        .cornerRadius(18)
        .onReceive(timer) { _ in
            dotCount += 1
        }
    }
}

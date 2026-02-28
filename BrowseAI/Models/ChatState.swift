import Foundation

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let role: Role
    let content: String
    let timestamp: Date

    enum Role: String {
        case user
        case assistant
    }

    init(role: Role, content: String) {
        self.role = role
        self.content = content
        self.timestamp = Date()
    }
}

class ChatState: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var isGenerating: Bool = false
    @Published var draftMessage: String = ""

    func addUserMessage(_ text: String) {
        let message = ChatMessage(role: .user, content: text)
        messages.append(message)
    }

    func addAssistantMessage(_ text: String) {
        let message = ChatMessage(role: .assistant, content: text)
        messages.append(message)
    }

    func clearMessages() {
        messages.removeAll()
    }
}

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var browserState: BrowserState
    @EnvironmentObject var chatState: ChatState
    @State private var isChatOpen = false

    var body: some View {
        ZStack(alignment: .trailing) {
            // Browser fills the full screen
            BrowserView()
                .environmentObject(browserState)

            // Chat panel slides in from the right
            if isChatOpen {
                ChatPanelView()
                    .environmentObject(chatState)
                    .environmentObject(browserState)
                    .frame(width: UIScreen.main.bounds.width * 0.4, alignment: .trailing)
                    .transition(.move(edge: .trailing))
                    .shadow(color: .black.opacity(0.3), radius: 10, x: -5)
            }
        }
        .overlay(alignment: .bottomTrailing) {
            if !isChatOpen {
                chatToggleButton
            }
        }
        .animation(.spring(response: 0.3), value: isChatOpen)
    }

    private var chatToggleButton: some View {
        Button {
            isChatOpen.toggle()
        } label: {
            Image(systemName: "bubble.left.and.bubble.right.fill")
                .font(.title2)
                .foregroundColor(.white)
                .padding(16)
                .background(Circle().fill(Color.blue))
                .shadow(radius: 4)
        }
        .padding(.trailing, 20)
        .padding(.bottom, 40)
    }
}

struct ChatPanelView: View {
    @EnvironmentObject var chatState: ChatState
    @EnvironmentObject var browserState: BrowserState

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("AI Agent")
                    .font(.headline)
                Spacer()
                Button {
                    withAnimation {
                        // parent will handle closing via binding
                    }
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.secondary)
                }
            }
            .padding()
            .background(Color(.systemBackground))

            Divider()

            // Chat view
            ChatView()
                .environmentObject(chatState)
                .environmentObject(browserState)
        }
        .background(Color(.systemBackground))
    }
}

import SwiftUI

@main
struct BrowseAIApp: App {
    @StateObject private var browserState = BrowserState()
    @StateObject private var chatState = ChatState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(browserState)
                .environmentObject(chatState)
        }
    }
}

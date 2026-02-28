import Foundation
import WebKit
import Combine

class BrowserState: ObservableObject {
    @Published var urlString: String = "https://www.google.com"
    @Published var pageTitle: String = ""
    @Published var isLoading: Bool = false
    @Published var canGoBack: Bool = false
    @Published var canGoForward: Bool = false
    @Published var currentURL: URL?

    /// The page text content, made available for the AI agent to read.
    @Published var pageContent: String = ""

    func navigateTo(_ input: String) {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)

        if let url = URL(string: trimmed), url.scheme != nil {
            urlString = trimmed
        } else if trimmed.contains(".") && !trimmed.contains(" ") {
            urlString = "https://\(trimmed)"
        } else {
            let query = trimmed.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? trimmed
            urlString = "https://www.google.com/search?q=\(query)"
        }
    }
}

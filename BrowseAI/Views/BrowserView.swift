import SwiftUI
import WebKit

struct BrowserView: View {
    @EnvironmentObject var browserState: BrowserState
    @State private var addressText: String = "https://www.google.com"
    @FocusState private var isAddressFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            // Toolbar
            toolbar
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color(.secondarySystemBackground))

            // Web content
            WebView(browserState: browserState)
                .ignoresSafeArea(edges: .bottom)
        }
        .onReceive(browserState.$urlString) { newURL in
            if !isAddressFocused {
                addressText = newURL
            }
        }
    }

    private var toolbar: some View {
        HStack(spacing: 10) {
            // Back
            Button {
                NotificationCenter.default.post(name: .webViewGoBack, object: nil)
            } label: {
                Image(systemName: "chevron.left")
                    .font(.body.weight(.medium))
            }
            .disabled(!browserState.canGoBack)

            // Forward
            Button {
                NotificationCenter.default.post(name: .webViewGoForward, object: nil)
            } label: {
                Image(systemName: "chevron.right")
                    .font(.body.weight(.medium))
            }
            .disabled(!browserState.canGoForward)

            // Reload
            Button {
                NotificationCenter.default.post(name: .webViewReload, object: nil)
            } label: {
                Image(systemName: browserState.isLoading ? "xmark" : "arrow.clockwise")
                    .font(.body.weight(.medium))
            }

            // Address bar
            HStack {
                if browserState.isLoading {
                    ProgressView()
                        .scaleEffect(0.7)
                }

                TextField("Search or enter URL", text: $addressText)
                    .textFieldStyle(.plain)
                    .autocapitalization(.none)
                    .disableAutocorrection(true)
                    .keyboardType(.URL)
                    .focused($isAddressFocused)
                    .onSubmit {
                        browserState.navigateTo(addressText)
                    }

                if !addressText.isEmpty && isAddressFocused {
                    Button {
                        addressText = ""
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .foregroundColor(.secondary)
                            .font(.caption)
                    }
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(Color(.systemBackground))
            .cornerRadius(10)
        }
    }
}

// MARK: - Notification names for WebView actions

extension Notification.Name {
    static let webViewGoBack = Notification.Name("webViewGoBack")
    static let webViewGoForward = Notification.Name("webViewGoForward")
    static let webViewReload = Notification.Name("webViewReload")
}

// MARK: - WKWebView wrapper

struct WebView: UIViewRepresentable {
    @ObservedObject var browserState: BrowserState

    func makeCoordinator() -> WebViewCoordinator {
        WebViewCoordinator(browserState: browserState)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        context.coordinator.webView = webView

        // Listen for navigation notifications
        context.coordinator.observeNotifications()

        // Load initial URL
        if let url = URL(string: browserState.urlString) {
            webView.load(URLRequest(url: url))
        }

        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        guard let url = URL(string: browserState.urlString) else { return }

        // Only load if the URL actually changed
        if webView.url?.absoluteString != browserState.urlString {
            webView.load(URLRequest(url: url))
        }
    }
}

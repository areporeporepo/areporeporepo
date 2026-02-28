import Foundation
import WebKit

class WebViewCoordinator: NSObject, WKNavigationDelegate {
    var browserState: BrowserState
    weak var webView: WKWebView?
    private var observers: [Any] = []

    init(browserState: BrowserState) {
        self.browserState = browserState
    }

    deinit {
        observers.forEach { NotificationCenter.default.removeObserver($0) }
    }

    func observeNotifications() {
        let back = NotificationCenter.default.addObserver(
            forName: .webViewGoBack, object: nil, queue: .main
        ) { [weak self] _ in
            self?.webView?.goBack()
        }

        let forward = NotificationCenter.default.addObserver(
            forName: .webViewGoForward, object: nil, queue: .main
        ) { [weak self] _ in
            self?.webView?.goForward()
        }

        let reload = NotificationCenter.default.addObserver(
            forName: .webViewReload, object: nil, queue: .main
        ) { [weak self] _ in
            guard let webView = self?.webView else { return }
            if webView.isLoading {
                webView.stopLoading()
            } else {
                webView.reload()
            }
        }

        observers = [back, forward, reload]
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        DispatchQueue.main.async {
            self.browserState.isLoading = true
            self.browserState.canGoBack = webView.canGoBack
            self.browserState.canGoForward = webView.canGoForward
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        DispatchQueue.main.async {
            self.browserState.isLoading = false
            self.browserState.pageTitle = webView.title ?? ""
            self.browserState.currentURL = webView.url
            self.browserState.urlString = webView.url?.absoluteString ?? ""
            self.browserState.canGoBack = webView.canGoBack
            self.browserState.canGoForward = webView.canGoForward
        }

        // Extract page text so the AI agent can reference it
        webView.evaluateJavaScript("document.body.innerText") { [weak self] result, _ in
            if let text = result as? String {
                DispatchQueue.main.async {
                    self?.browserState.pageContent = text
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        DispatchQueue.main.async {
            self.browserState.isLoading = false
        }
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        decisionHandler(.allow)
    }
}

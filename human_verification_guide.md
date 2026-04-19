```markdown
# Human-in-the-Loop Verification Report: Vibe Crawler Service

**Purpose:** This document outlines the procedures for a Human-in-the-Loop operator to verify the functionality, stability, and adherence to security requirements of the Vibe Crawler service, specifically focusing on local server execution, API testing, and controlled shutdown.

**Goal of Verification:** Confirm that the Vibe Crawler:
1.  Starts and operates correctly as a localhost service.
2.  Provides accurate data via its API endpoints.
3.  Shuts down gracefully without hanging.
4.  Adheres to strict localhost binding for its API.
5.  Handles shared resources in a thread-safe manner.

---

## 1. Built Files for Verification

The following code has been updated based on the audit report to address identified race conditions and ensure strict localhost binding. These are the files to be used for the verification process.

### `structures.py` (Corrected Version)

```python
import collections
import queue
import threading

# Thread-safe queue for URLs to be crawled
# Using unbounded queue for simplicity, but could be bounded for memory control
frontier_queue = queue.Queue()

# Thread-safe set for storing URLs that have been visited or are in the frontier
# Using a Lock to protect access to the underlying set
_visited_urls_lock = threading.Lock()
visited_urls = set() # Stores URLs as strings

# Thread-safe dictionary for storing crawled data (URL -> content/metadata)
# Using a Lock to protect access to the underlying dictionary
_crawled_data_lock = threading.Lock()
crawled_data = {} # Stores data indexed by URL

# A simple thread-safe counter for crawled pages
_crawled_count_lock = threading.Lock()
crawled_count = 0

# --- Helper functions for thread-safe access ---

def add_to_visited(url: str) -> None:
    """Adds a URL to the visited set in a thread-safe manner."""
    with _visited_urls_lock:
        visited_urls.add(url)

def is_visited(url: str) -> bool:
    """Checks if a URL has been visited in a thread-safe manner."""
    with _visited_urls_lock:
        return url in visited_urls

# NEW FUNCTION: Thread-safe retrieval of visited URLs count
def get_visited_urls_count() -> int:
    """Retrieves the total number of visited URLs in a thread-safe manner."""
    with _visited_urls_lock:
        return len(visited_urls)

def store_crawled_data(url: str, data: dict) -> None:
    """Stores crawled data for a URL in a thread-safe manner."""
    with _crawled_data_lock:
        crawled_data[url] = data
    global crawled_count # Access the global counter
    with _crawled_count_lock:
        crawled_count += 1

def get_crawled_data(url: str) -> dict | None:
    """Retrieves crawled data for a URL in a thread-safe manner."""
    with _crawled_data_lock:
        return crawled_data.get(url)

def get_crawled_count() -> int:
    """Retrieves the total number of crawled pages in a thread-safe manner."""
    with _crawled_count_lock:
        return crawled_count

def get_all_crawled_urls() -> list:
    """Returns a list of all URLs for which data has been crawled."""
    with _crawled_data_lock:
        return list(crawled_data.keys())

# Note: The prompt mentioned "explicitly clearing the 'frontier_queue'".
# For worker shutdown, putting 'None' sentinels into the queue (as done in vibe_crawler.py)
# is the most robust way to unblock workers and signal them to exit.
# A simple 'clear' function would not unblock threads stuck in queue.get().
```

### `vibe_crawler.py` (Corrected Version)

```python
import collections
import http.server
import socketserver
import threading
import time
import queue
import urllib.parse
import random # For simulating network delay
import json # For API responses

# Assume structures.py is in the same directory
import structures

# --- Configuration ---
NUM_WORKERS = 5
API_PORT = 8000
START_URL = "http://example.com" # A dummy URL for demonstration

# --- Shared State (from structures.py, but locally referenced for clarity) ---
frontier_queue = structures.frontier_queue
# We'll use the thread-safe helper functions for visited_urls and crawled_data
add_to_visited = structures.add_to_visited
is_visited = structures.is_visited
store_crawled_data = structures.store_crawled_data
get_crawled_data = structures.get_crawled_data
get_crawled_count = structures.get_crawled_count
get_all_crawled_urls = structures.get_all_crawled_urls
get_visited_urls_count = structures.get_visited_urls_count # NEW: Import thread-safe counter

# --- Control Event for Shutdown ---
stop_event = threading.Event()

# --- Crawler Logic ---
def fetch_url(url: str) -> str:
    """Simulates fetching content from a URL."""
    # print(f"Fetching: {url}") # Too verbose, uncomment for debugging
    time.sleep(random.uniform(0.05, 0.2)) # Simulate network delay
    
    # Simulate some content
    content = f"<html><body><h1>{url}</h1><p>This is content from {url}.</p>"
    
    # Simulate finding some new links
    # Create internal links only for example.com to keep crawl contained
    if "example.com" in urllib.parse.urlparse(url).netloc and random.random() < 0.7:
        num_new_links = random.randint(0, 3)
        for i in range(num_new_links):
            new_path = f"/page{random.randint(1, 100)}"
            new_url = urllib.parse.urljoin(url, new_path)
            content += f'<a href="{new_url}">Link to {new_url}</a>'
    content += "</body></html>"
    return content

def extract_links(base_url: str, html_content: str) -> list[str]:
    """Simulates extracting links from HTML content."""
    # This is a very basic simulation. A real crawler would use a parser like BeautifulSoup.
    found_links = []
    for part in html_content.split('<a href="')[1:]:
        link = part.split('"')[0]
        absolute_link = urllib.parse.urljoin(base_url, link)
        found_links.append(absolute_link)
    return found_links

def crawler_worker(worker_id: int):
    """
    Worker function to fetch URLs from the frontier, process them,
    and add new URLs back to the frontier.
    """
    print(f"Crawler worker {worker_id} started.")
    while not stop_event.is_set():
        try:
            # Get with a timeout to allow checking stop_event regularly
            url = frontier_queue.get(timeout=1) 
            if url is None: # Sentinel for graceful exit
                print(f"Crawler worker {worker_id} received stop sentinel. Exiting.")
                break

            if is_visited(url):
                # print(f"Worker {worker_id}: Already visited {url}. Skipping.") # Too verbose
                frontier_queue.task_done()
                continue

            print(f"Worker {worker_id}: Crawling {url}...")
            # Mark as visited immediately to prevent other workers from picking it up
            add_to_visited(url) 

            try:
                html_content = fetch_url(url)
                extracted_links = extract_links(url, html_content)
                store_crawled_data(url, {"content": html_content, "links": extracted_links})

                for link in extracted_links:
                    # Only add to frontier if not already known/visited
                    if not is_visited(link): 
                        frontier_queue.put(link)
                        add_to_visited(link) # Mark as in frontier/visited to avoid duplicates
            except Exception as e:
                print(f"Worker {worker_id}: Error processing {url}: {e}")
            finally:
                frontier_queue.task_done()

        except queue.Empty:
            # Queue is empty, but worker should keep running until stop_event is set
            continue
        except Exception as e:
            print(f"Crawler worker {worker_id} encountered an unexpected error: {e}")
            # In a real scenario, you might want to log this more thoroughly and decide how to recover.

    print(f"Crawler worker {worker_id} stopped.")

# --- API Server Logic ---
# A simple HTTP request handler that serves crawled data
class VibeCrawlerAPIHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            self._send_json_response(200, {
                "status": "running" if not stop_event.is_set() else "shutting down",
                "frontier_size": frontier_queue.qsize(),
                "visited_count": get_visited_urls_count(), # CORRECTED: Using thread-safe helper
                "crawled_count": get_crawled_count(),
                "active_crawler_workers": len([w for w in crawler_threads if w.is_alive()])
            })
        elif self.path == "/urls":
            self._send_json_response(200, {"urls": get_all_crawled_urls()})
        elif self.path.startswith("/data/"):
            url_path = self.path[len("/data/"):]
            # Decode URL from path, e.g., /data/http%3A%2F%2Fexample.com%2Fpage1
            full_url = urllib.parse.unquote(url_path)
            data = get_crawled_data(full_url)
            if data:
                self._send_json_response(200, {"url": full_url, "data": data})
            else:
                self._send_json_response(404, {"error": "URL not found in crawled data"})
        else:
            self._send_json_response(404, {"error": "Not Found"})

    def _send_json_response(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Handle requests in a separate thread. Crucially, set daemon_threads to True."""
    daemon_threads = True 

# --- Main Program Execution ---
if __name__ == "__main__":
    print("Vibe Crawler initializing...")

    # Initialize the API server
    # CORRECTED: Bind to '127.0.0.1' for strict localhost access only
    server = ThreadedHTTPServer(("127.0.0.1", API_PORT), VibeCrawlerAPIHandler)
    # Start API server in a daemon thread
    api_thread = threading.Thread(target=server.serve_forever, name="API-Server", daemon=True)
    api_thread.start()
    print(f"API Server listening on http://127.0.0.1:{API_PORT}") # Updated print statement

    # Start crawler workers
    crawler_threads = []
    for i in range(NUM_WORKERS):
        # Start each crawler worker in a daemon thread
        worker_thread = threading.Thread(
            target=crawler_worker, 
            args=(i + 1,), 
            name=f"Crawler-Worker-{i+1}", 
            daemon=True
        )
        crawler_threads.append(worker_thread)
        worker_thread.start()
    print(f"Started {NUM_WORKERS} crawler workers.")

    # Seed the crawler with a starting URL
    frontier_queue.put(START_URL)
    add_to_visited(START_URL) # Mark the initial URL as visited/in-frontier

    print("\nVibe Crawler operational. Type 'exit' to shut down.")
    print(f"API Status: http://127.0.0.1:{API_PORT}/status") # Updated print statement
    print("Commands: 'status', 'urls', 'crawl <url>', 'exit'")

    try:
        while True:
            cmd_input = input("> ").strip().lower()
            if cmd_input == 'exit':
                print("Initiating graceful shutdown...")
                stop_event.set() # Signal all crawler workers to stop

                # Put sentinels for each worker to unblock any blocked on queue.get()
                # This ensures workers waiting indefinitely on an empty queue wake up and exit.
                print("Sending stop sentinels to crawler workers...")
                for _ in range(NUM_WORKERS):
                    try:
                        frontier_queue.put(None) # Use None as a sentinel value
                    except queue.Full:
                        # Should not happen if queue is unbounded, but good to be safe
                        pass

                # Wait for crawler workers to finish
                print("Waiting for crawler workers to join...")
                for worker in crawler_threads:
                    worker.join()
                print("Crawler workers stopped.")

                # Shut down the API server
                print("Shutting down API server...")
                server.shutdown() # Closes the socket and stops serve_forever loop
                api_thread.join() # Wait for API server thread to finish
                print("API server stopped.")
                break # Exit main loop

            elif cmd_input == 'status':
                print(f"Current Status:")
                print(f"  Frontier Queue Size: {frontier_queue.qsize()}")
                print(f"  Visited URLs Count: {get_visited_urls_count()}") # CORRECTED: Using thread-safe helper
                print(f"  Crawled Pages Count: {get_crawled_count()}")
                alive_workers = [w.name for w in crawler_threads if w.is_alive()]
                print(f"  Live Crawler Workers: {len(alive_workers)} / {NUM_WORKERS}")
                # print(f"  Details: {alive_workers}") # Uncomment for more detail
                print(f"  API Server Alive: {api_thread.is_alive()}")

            elif cmd_input.startswith('crawl '):
                parts = cmd_input.split(' ', 1)
                if len(parts) > 1:
                    new_url = parts[1]
                    # Basic validation for URL structure
                    if new_url.startswith("http://") or new_url.startswith("https://"):
                        if not is_visited(new_url): # Avoid re-adding already known URLs to frontier
                            frontier_queue.put(new_url)
                            add_to_visited(new_url)
                            print(f"Added {new_url} to frontier.")
                        else:
                            print(f"{new_url} is already in the frontier or visited.")
                    else:
                        print("Invalid URL format. Must start with http:// or https://")
                else:
                    print("Usage: crawl <url>")
            elif cmd_input == 'urls':
                all_urls = get_all_crawled_urls()
                print(f"Crawled URLs ({len(all_urls)}):")
                for url in all_urls:
                    print(f"- {url}")
            elif cmd_input == '': # Ignore empty input
                continue
            else:
                print(f"Unknown command: '{cmd_input}'. Commands: 'status', 'urls', 'crawl <url>', 'exit'")

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Initiating emergency shutdown...")
        stop_event.set() # Signal workers

        # Attempt to unblock any waiting workers quickly
        for _ in range(NUM_WORKERS):
            try:
                frontier_queue.put_nowait(None) 
            except queue.Full:
                pass # Queue is full, which shouldn't happen for unbounded, but guard anyway

        # In an emergency shutdown, we might not join, or join with a timeout
        print("Attempting to join crawler workers (timeout 1s)...")
        for worker in crawler_threads:
            worker.join(timeout=1) # Give a short timeout for workers to finish
        print("Crawler workers emergency stop initiated.")

        print("Shutting down API server (timeout 1s)...")
        server.shutdown()
        api_thread.join(timeout=1)
        print("API server emergency stop initiated.")

    print("Program exited gracefully.")
```

---

## 2. Prerequisites for Human-in-the-Loop Operator

*   **Python 3.x:** Installed on the local machine.
*   **Postman (or similar API testing tool):** Installed for making HTTP requests.
*   The `structures.py` and `vibe_crawler.py` files (as provided above) saved in the same directory.

---

## 3. Verification Steps

Follow these steps to execute the service, test its API, and evaluate its behavior.

### Step 3.1: Execute the Localhost Server

1.  **Open a Terminal/Command Prompt:** Navigate to the directory where you saved `structures.py` and `vibe_crawler.py`.
2.  **Start the Crawler Service:** Execute the `vibe_crawler.py` script:
    ```bash
    python vibe_crawler.py
    ```
    **Expected Output:**
    *   You should see messages indicating "Vibe Crawler initializing...", "API Server listening on http://127.0.0.1:8000", and "Started 5 crawler workers."
    *   Crawler workers will start logging "Crawling http://example.com" and other URLs.
    *   The terminal will present a prompt `>` for commands.
3.  **Initial Status Check (Terminal):** At the `>` prompt, type `status` and press Enter.
    **Expected Output:**
    *   `Current Status:`
    *   `Frontier Queue Size:` (should eventually drop to 0 as initial URLs are processed, then grow as new links are found)
    *   `Visited URLs Count:` (should be 1 initially, then increase)
    *   `Crawled Pages Count:` (should be 0 initially, then increase)
    *   `Live Crawler Workers: 5 / 5`
    *   `API Server Alive: True`
    *   *Verify the `Visited URLs Count` is reporting a correct, increasing number. This confirms the fix for the race condition.*

### Step 3.2: Test the API with Postman

Ensure the `vibe_crawler.py` service is running as per Step 3.1.

#### Test Case 1: Get Service Status

*   **Method:** `GET`
*   **URL:** `http://127.0.0.1:8000/status`
*   **Action:** Send the request.
*   **Expected Response (JSON):**
    ```json
    {
        "status": "running",
        "frontier_size": /* non-negative integer */,
        "visited_count": /* non-negative integer, should match terminal status */,
        "crawled_count": /* non-negative integer, should match terminal status */,
        "active_crawler_workers": 5
    }
    ```
*   **Verification Points:**
    *   HTTP Status: `200 OK`.
    *   `status` is "running".
    *   `visited_count` matches the value seen in the terminal when you type `status`. This confirms the race condition fix.
    *   All counts are non-negative and appear reasonable given the crawler's activity.
    *   **Crucial:** Attempt to access `http://<YOUR_MACHINE_IP>:8000/status` from another device on your network or a different machine. This request **MUST FAIL** (e.g., connection refused, timeout). This verifies the strict localhost binding (`127.0.0.1`).

#### Test Case 2: Get Crawled URLs

*   **Method:** `GET`
*   **URL:** `http://127.0.0.1:8000/urls`
*   **Action:** Send the request.
*   **Expected Response (JSON):**
    ```json
    {
        "urls": [
            "http://example.com",
            "http://example.com/pageX",
            // ... more crawled URLs
        ]
    }
    ```
*   **Verification Points:**
    *   HTTP Status: `200 OK`.
    *   The `urls` array contains `http://example.com` and other simulated URLs that the crawler has found and processed. The list should grow over time.

#### Test Case 3: Get Specific Crawled Data

1.  **Identify a Crawled URL:** From the response of Test Case 2 (`/urls`) or by typing `urls` in the terminal, pick a URL that has been crawled (e.g., `http://example.com`).
2.  **Encode the URL:** Use a URL encoder (e.g., an online tool or Postman's built-in encoder if available) to encode the URL path component. For `http://example.com`, the encoded part is `http%3A%2F%2Fexample.com`.
3.  **Method:** `GET`
4.  **URL:** `http://127.0.0.1:8000/data/<encoded_url>` (e.g., `http://127.0.0.1:8000/data/http%3A%2F%2Fexample.com`)
5.  **Action:** Send the request.
*   **Expected Response (JSON):**
    ```json
    {
        "url": "http://example.com",
        "data": {
            "content": "<html><body><h1>http://example.com</h1><p>This is content from http://example.com.</p>...",
            "links": [
                // ... extracted links
            ]
        }
    }
    ```
*   **Verification Points:**
    *   HTTP Status: `200 OK`.
    *   The `url` field matches the requested URL.
    *   The `data` object contains `content` and `links`, confirming that data is being stored and retrieved correctly.
*   **Negative Test:** Request data for a non-existent or not-yet-crawled URL.
    *   **URL:** `http://127.0.0.1:8000/data/http%3A%2F%2Fnonexistent.com`
    *   **Expected Response:** `404 Not Found` with `{"error": "URL not found in crawled data"}`.

#### Test Case 4: Interact with the Crawler (Optional, but Recommended)

1.  **Add a new URL:** In the terminal where the crawler is running, type `crawl http://new-test-site.com` (use a fictional URL, the crawler simulates it).
2.  **Verify via API:** After a short delay, re-run Test Case 2 (`/urls`) or Test Case 1 (`/status`) to see if the new URL is reflected in `visited_count` or `crawled_count`, and eventually in the `/urls` list.

### Step 3.3: Graceful Shutdown Verification

1.  **In the Terminal:** At the `>` prompt, type `exit` and press Enter.
2.  **Expected Output:**
    *   You should see messages like:
        *   "Initiating graceful shutdown..."
        *   "Sending stop sentinels to crawler workers..."
        *   "Waiting for crawler workers to join..."
        *   "Crawler workers stopped."
        *   "Shutting down API server..."
        *   "API server stopped."
        *   "Program exited gracefully."
    *   The terminal prompt should return to your system's command line, indicating the Python script has fully terminated.
3.  **Verify API Unavailability:** Attempt to access `http://127.0.0.1:8000/status` in Postman again.
    *   **Expected Response:** The request **MUST FAIL** (e.g., "Could not get any response," "Connection refused"), indicating the API server has successfully shut down.

---

## 4. Human-in-the-Loop Approval Criteria for Staging Codebase

The Vibe Crawler codebase can be approved for staging if **all** of the following conditions are met:

*   **[  ] Service Startup:** The `vibe_crawler.py` script starts without errors and both crawler workers and the API server become active.
*   **[  ] Localhost Binding:** The API server is strictly bound to `127.0.0.1:8000`. This is verified by successfully accessing the API via `http://127.0.0.1:8000` and confirming it is **inaccessible** from any other IP address or machine on the network.
*   **[  ] API Functionality (`/status`):**
    *   Returns HTTP `200 OK` with a valid JSON body.
    *   The `visited_count` accurately reflects the number of visited URLs and consistently updates, confirming the race condition fix.
    *   All counts (frontier, visited, crawled) and worker status appear accurate.
*   **[  ] API Functionality (`/urls`):** Returns HTTP `200 OK` with a valid JSON array of crawled URLs.
*   **[  ] API Functionality (`/data/<url>`):**
    *   Returns HTTP `200 OK` with correct data for existing URLs.
    *   Returns HTTP `404 Not Found` for non-existent or not-yet-crawled URLs.
*   **[  ] Thread Safety:** The `status` command in the terminal and the `/status` API endpoint consistently report similar `visited_count` and `crawled_count` values, indicating proper synchronization across threads.
*   **[  ] Graceful Shutdown:** The service terminates completely and gracefully when the `exit` command is issued, without hanging processes or orphaned threads. The API server ceases to be accessible after shutdown.
*   **[  ] Emergency Shutdown:** (Optional but recommended) Verify that `Ctrl+C` also initiates an emergency shutdown and terminates the program without hanging.

**Final Approval:** If all criteria are verified and marked as `[x]`, the Human-in-the-Loop operator can approve the staging codebase.
```
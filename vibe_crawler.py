import threading
import http.server
import socketserver
import json
import time
import queue
from urllib.parse import urlparse, urljoin, parse_qs
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser
import re # For basic keyword extraction
import sys # For sys.stdout.flush()

# --- Thread-Safe Data Structures ---

class ThreadSafeVisitedSet:
    """
    A thread-safe set to store URLs that have been visited.
    This fulfills the "Uniqueness Guarantee" (F.1.2) by ensuring no single URL
    is crawled or processed more than once, and adheres to "Concurrency and Thread Safety" (5.1)
    by using native Python threading locks.
    """
    def __init__(self):
        self._visited = set()
        self._lock = threading.Lock()

    def add(self, url: str) -> bool:
        """
        Adds a URL to the set if it hasn't been visited before.
        Returns True if the URL was added, False if it was already present.
        Ensures atomic operation using a lock.
        """
        with self._lock:
            if url in self._visited:
                return False
            self._visited.add(url)
            return True

    def contains(self, url: str) -> bool:
        """
        Checks if a URL is present in the visited set.
        Performs a read operation under a lock.
        """
        with self._lock:
            return url in self._visited

    def size(self) -> int:
        """
        Returns the number of unique URLs currently in the visited set.
        """
        with self._lock:
            return len(self._visited)

    def __len__(self) -> int:
        """Allows len(visited_set) for convenience."""
        return self.size()

    def __contains__(self, url: str) -> bool:
        """Allows 'url in visited_set' for convenience."""
        return self.contains(url)

    def __str__(self):
        """String representation for debugging."""
        with self._lock:
            return f"ThreadSafeVisitedSet(size={len(self._visited)})"

class ThreadSafeIndexMap:
    """
    A thread-safe inverted index mapping keywords to a list of
    (relevant_url, origin_url, depth, frequency) tuples.
    This supports "Live Indexing Support" (F.2.2) by allowing the Searcher
    to read while the Indexer actively writes, preventing data corruption
    through "Concurrency and Thread Safety" (5.1).

    The index now stores frequency information for relevancy ranking.
    Structure: { keyword: { (relevant_url, origin_url, depth): frequency, ... } }
    This ensures uniqueness per (keyword, url, depth) and stores the highest frequency
    encountered for that combination.
    """
    def __init__(self):
        # Structure: { keyword: { (relevant_url, origin_url, depth): frequency } }
        self._index = {}
        # A single lock is used for simplicity and safety, ensuring atomicity for both
        # read and write operations on the index, as specified in (5.1).
        self._lock = threading.Lock()

    def add(self, keyword: str, relevant_url: str, origin_url: str, depth: int, frequency: int):
        """
        Adds or updates a keyword-URL mapping with its frequency to the index.
        Keywords are normalized to lowercase. If an entry for (keyword, url, depth)
        already exists, its frequency is updated if the new frequency is higher.
        """
        if not keyword or frequency <= 0:
            return # Skip empty keywords or non-positive frequencies

        keyword = keyword.lower() # Standardize keyword casing
        
        # The URL key tuple matches the required search result format (F.2.1) prefix.
        url_key = (relevant_url, origin_url, depth)

        with self._lock:
            if keyword not in self._index:
                self._index[keyword] = {}
            
            # Store the maximum frequency found for this (keyword, url_key) combination.
            # This handles cases where a page might be processed multiple times (though
            # visited_set should prevent this), or if parsing yields different counts.
            current_freq = self._index[keyword].get(url_key, 0)
            self._index[keyword][url_key] = max(current_freq, frequency)

    def search(self, query_keyword: str) -> list[tuple[str, str, int, int]]:
        """
        Searches the index for the given keyword and returns a list of
        (relevant_url, origin_url, depth, frequency) tuples.
        Returns an empty list if no matches are found. The results are a copy
        to prevent external modification of the internal index state.
        """
        if not query_keyword:
            return []

        query_keyword = query_keyword.lower() # Standardize query keyword casing

        with self._lock:
            page_freq_map = self._index.get(query_keyword, {})
            # Convert the internal dict-of-dicts representation to a list of 4-tuples.
            # This format is now ready for sorting by frequency.
            results = [
                (url, origin, depth, freq)
                for (url, origin, depth), freq in page_freq_map.items()
            ]
            return results

    def size(self) -> int:
        """
        Returns the total number of unique keywords currently in the index.
        """
        with self._lock:
            return len(self._index)

    def total_entries(self) -> int:
        """
        Returns the total count of (keyword, url_info) mappings across all keywords,
        where each url_info is a unique (relevant_url, origin_url, depth) combination.
        """
        with self._lock:
            return sum(len(v) for v in self._index.values())

    def __str__(self):
        """String representation for debugging."""
        with self._lock:
            return f"ThreadSafeIndexMap(keywords={len(self._index)}, entries={self.total_entries()})"


# --- Localhost API Structural Design ---

class VibeCrawlerHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """
    Custom HTTP Server designed to run exclusively on localhost (5.4 Execution Environment).
    It uses `socketserver.ThreadingMixIn` to handle incoming requests concurrently,
    demonstrating "Concurrency Management" (2. Project Goals).
    This server holds references to the shared `ThreadSafeVisitedSet` and `ThreadSafeIndexMap`,
    making them accessible to request handlers.
    """
    daemon_threads = True # Allows server threads to exit when the main program exits cleanly.

    def __init__(self, server_address, RequestHandlerClass, visited_set, index_map, frontier_queue=None, crawler_is_running_event=None):
        super().__init__(server_address, RequestHandlerClass)
        self.visited_set = visited_set
        self.index_map = index_map
        # The frontier_queue is included for dashboard metrics ("Current Queue Depth")
        # as per "System Visibility & UI (Dashboard)" requirements.
        self.frontier_queue = frontier_queue # Assumes a thread-safe queue instance will be passed.
        self.crawler_is_running_event = crawler_is_running_event # An event to indicate crawler status

class VibeCrawlerRequestHandler(http.server.BaseHTTPRequestHandler):
    """
    Request handler for the VibeCrawler's "Search API" (6. High-Level Architecture Flow, Step 7)
    and "System Visibility & UI (Dashboard)".
    It processes GET requests for search queries and system metrics.
    """
    def _set_headers(self, status_code=200, content_type='application/json'):
        """Helper to set common HTTP response headers."""
        self.send_response(status_code)
        self.send_header('Content-type', content_type)
        self.end_headers()

    def do_GET(self):
        """Handles GET requests for different API endpoints."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query_params = parse_qs(parsed_path.query)

        if path == '/search':
            self._handle_search(query_params)
        elif path == '/dashboard':
            self._handle_dashboard()
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Not Found'}).encode('utf-8'))

    def _handle_search(self, query_params):
        """
        Handles search requests, fulfilling "Real-Time Querying" (F.2.1).
        Accepts a 'q' query parameter and returns a structured list of results
        from the live index. Relevancy ranking logic would be applied here (F.2.3).
        """
        query = query_params.get('q', [None])[0]
        if not query:
            self._set_headers(400)
            self.wfile.write(json.dumps({'error': 'Missing query parameter "q"'}).encode('utf-8'))
            return

        # Access the shared index_map from the server instance.
        # This now returns tuples of (relevant_url, origin_url, depth, frequency)
        results_with_frequency = self.server.index_map.search(query)

        # "Relevancy Ranking" (F.2.3): Sort results by frequency (descending).
        # Higher frequency of the keyword on a page implies higher relevancy for that keyword.
        # The frequency is the 4th element (index 3) in the tuple.
        sorted_results = sorted(results_with_frequency, key=lambda x: x[3], reverse=True)

        formatted_results = []
        for relevant_url, origin_url, depth, frequency in sorted_results:
            formatted_results.append({
                'relevant_url': relevant_url,
                'origin_url': origin_url,
                'depth': depth,
                'frequency': frequency # Include frequency in the API response
            })

        self._set_headers(200)
        self.wfile.write(json.dumps({'query': query, 'results': formatted_results}).encode('utf-8'))

    def _handle_dashboard(self):
        """
        Handles requests for the "Real-time Dashboard" (System Visibility & UI).
        It collects and displays "Metrics to Track" from the system's live state.
        """
        metrics = {}

        # Current Indexing Progress: total URLs processed vs. URLs currently queued.
        metrics['visited_urls_count'] = self.server.visited_set.size()
        metrics['indexed_keywords_count'] = self.server.index_map.size()
        metrics['indexed_entries_count'] = self.server.index_map.total_entries()

        # Current Queue Depth: live size of the Frontier Queue.
        metrics['frontier_queue_depth'] = 0
        if self.server.frontier_queue:
            try:
                metrics['frontier_queue_depth'] = self.server.frontier_queue.qsize()
            except AttributeError:
                metrics['frontier_queue_depth'] = 'N/A' # In case of a custom queue without qsize()

        # Back-pressure/Throttling Status: indicator.
        # This status is managed by the crawler's workload regulation (F.1.3).
        metrics['throttling_status'] = 'Active (Crawler respects crawl_delay)'

        # Crawler status
        metrics['crawler_status'] = 'Running' if (self.server.crawler_is_running_event and self.server.crawler_is_running_event.is_set()) else 'Stopped'

        self._set_headers(200)
        self.wfile.write(json.dumps({'dashboard_metrics': metrics}).encode('utf-8'))


# --- Crawler Implementation ---

class LinkAndTextExtractor(HTMLParser):
    """
    A custom HTML parser to extract links (hrefs from <a> tags) and visible text.
    """
    def __init__(self):
        super().__init__()
        self.links = []
        self.text_content = []
        self._recording_text = False # Simple state for text extraction

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href':
                    self.links.append(value)
        # Consider common tags that contain visible text
        if tag in ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span', 'li', 'td', 'th', 'title']:
            self._recording_text = True

    def handle_endtag(self, tag):
        if tag in ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span', 'li', 'td', 'th', 'title']:
            self._recording_text = False
            # Add a space to separate text blocks for better keyword extraction
            if self.text_content and self.text_content[-1] != ' ':
                self.text_content.append(' ')


    def handle_data(self, data):
        if self._recording_text:
            stripped_data = data.strip()
            if stripped_data:
                self.text_content.append(stripped_data)

    def get_links(self) -> list[str]:
        return self.links

    def get_text(self) -> str:
        return ' '.join(self.text_content)

    def reset(self):
        super().reset()
        self.links = []
        self.text_content = []
        self._recording_text = False

class Crawler:
    """
    The core recursive crawler logic, managing the frontier, visited URLs, and indexing.
    Implements backpressure and depth limits. Workers persist and wait for tasks.
    """
    USER_AGENT = 'VibeCrawler/1.0 (Python native crawler; contact: example@example.com)'
    # Basic list of common stop words for simple keyword filtering
    STOP_WORDS = {
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he', 'in',
        'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'were', 'will', 'with'
    }

    _POISON_PILL = (None, None, None) # Special tuple to signal workers to stop

    def __init__(self, visited_set: ThreadSafeVisitedSet, index_map: ThreadSafeIndexMap,
                 frontier_queue: queue.Queue, max_depth: int, crawl_delay_seconds: float = 0.5,
                 global_crawler_event: threading.Event = None): # Event for dashboard status
        self.visited_set = visited_set
        self.index_map = index_map
        self.frontier_queue = frontier_queue # Stores (url, depth, origin_url) tuples
        self.max_depth = max_depth
        self.crawl_delay_seconds = crawl_delay_seconds
        
        self._workers: list[threading.Thread] = []
        self._is_workers_running = False # Flag to know if worker threads have been spawned
        # _stop_event not strictly needed with poison pill but can be used for other internal control
        self._stop_event = threading.Event() 
        
        self.global_crawler_event = global_crawler_event # Event for dashboard/overall system status

    def _normalize_url(self, base_url: str, link: str) -> str | None:
        """
        Normalizes a URL, resolving relative paths and filtering out unwanted schemes.
        Returns a cleaned absolute URL or None if invalid.
        """
        # Resolve relative URLs
        absolute_url = urljoin(base_url, link)
        
        # Parse the URL to examine components
        parsed = urlparse(absolute_url)

        # Filter out non-http/https schemes
        if parsed.scheme not in ['http', 'https']:
            return None
        
        # Remove fragment identifiers (e.g., #section) as they don't represent unique pages for crawling
        clean_url = parsed._replace(fragment="").geturl()

        return clean_url

    def _extract_keywords(self, text: str) -> dict[str, int]:
        """
        Extracts keywords from text content and counts their frequencies.
        Converts to lowercase, splits by non-alphanumeric, filters stop words.
        Returns a dictionary of {keyword: frequency}.
        """
        # Split by non-alphanumeric characters, convert to lowercase
        words = re.findall(r'\b\w+\b', text.lower())
        
        keyword_frequencies = {}
        for word in words:
            # Filter out stop words and single-character words (unless they are numbers)
            if word not in self.STOP_WORDS and (len(word) > 1 or word.isdigit()):
                keyword_frequencies[word] = keyword_frequencies.get(word, 0) + 1
        return keyword_frequencies

    def _fetch_and_parse(self, url: str) -> tuple[str | None, list[str], str]:
        """
        Fetches the HTML content of a URL and parses it for links and text.
        Returns (html_content, links, text) or (None, [], "") on error.
        """
        try:
            req = Request(url, headers={'User-Agent': self.USER_AGENT})
            with urlopen(req, timeout=10) as response:
                content_type = response.info().get_content_type()
                if not content_type or not content_type.startswith('text/html'):
                    # print(f"Skipping non-HTML content for {url}: {content_type}")
                    return None, [], ""

                html_bytes = response.read()
                # Attempt to decode, falling back to a common encoding if original fails
                try:
                    html_content = html_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        html_content = html_bytes.decode('latin-1')
                    except UnicodeDecodeError:
                        # print(f"Failed to decode HTML for {url}")
                        return None, [], ""
                
                parser = LinkAndTextExtractor()
                parser.feed(html_content)
                links = parser.get_links()
                text = parser.get_text()
                parser.close()
                return html_content, links, text

        except HTTPError as e:
            # print(f"HTTP Error {e.code} for {url}: {e.reason}")
            pass
        except URLError as e:
            # print(f"URL Error for {url}: {e.reason}")
            pass
        except Exception as e:
            # print(f"Generic error fetching {url}: {e}")
            pass
        return None, [], ""

    def _process_page(self, current_url: str, html_content: str, extracted_links: list[str],
                      page_text: str, depth: int, origin_url: str):
        """
        Processes the content of a crawled page: adds keywords with frequencies to index and
        new URLs to the frontier.
        """
        # Add keywords with their frequencies to the index
        keyword_frequencies = self._extract_keywords(page_text)
        for keyword, frequency in keyword_frequencies.items():
            # Pass the frequency to the index map's add method
            self.index_map.add(keyword, current_url, origin_url, depth, frequency)

        # Add new links to frontier if within depth limit
        if depth < self.max_depth:
            for link in extracted_links:
                normalized_link = self._normalize_url(current_url, link)
                if normalized_link and self.visited_set.add(normalized_link):
                    # print(f"  Adding to frontier: {normalized_link} (Depth: {depth + 1})")
                    self.frontier_queue.put((normalized_link, depth + 1, current_url))

    def _worker_thread_loop(self):
        """
        Worker function for crawler threads. Continuously fetches URLs from the frontier
        and processes them. Blocks on the queue until items are available or a stop signal.
        """
        # print(f"Crawler worker {threading.get_ident()} started.")

        while True:
            try:
                # Blocks indefinitely until an item is available
                url_info = self.frontier_queue.get() 
                
                # Check for poison pill to exit gracefully
                if url_info == self._POISON_PILL:
                    # Signal task completion for the poison pill, then exit
                    self.frontier_queue.task_done()
                    break 

                current_url, depth, origin_url = url_info
                
                # print(f"Worker {threading.get_ident()} crawling: {current_url} (Depth: {depth})")

                html_content, links, text = self._fetch_and_parse(current_url)
                if html_content:
                    self._process_page(current_url, html_content, links, text, depth, origin_url)
                
                self.frontier_queue.task_done()
                time.sleep(self.crawl_delay_seconds) # Apply backpressure
            except Exception as e:
                # print(f"Crawler worker error: {e}")
                self.frontier_queue.task_done() # Mark task as done even if it failed
        
        # print(f"Crawler worker {threading.get_ident()} stopped.")

    def start_workers(self, num_workers: int = 5):
        """
        Starts the worker threads if they are not already running.
        This method should be called once at the start of the application.
        """
        if self._is_workers_running:
            return

        self._workers = []
        for i in range(num_workers):
            worker = threading.Thread(target=self._worker_thread_loop, daemon=True)
            self._workers.append(worker)
            worker.start()
        self._is_workers_running = True
        
        if self.global_crawler_event:
            self.global_crawler_event.set() # Indicate that crawler workers are active
        print(f"Started {num_workers} crawler workers.")

    def add_seeds(self, seed_urls: list[str]):
        """
        Adds new seed URLs to the frontier queue.
        Requires workers to be started via `start_workers` beforehand.
        """
        if not self._is_workers_running:
            print("Crawler workers are not running. Please start them first before adding seeds.")
            return

        added_any = False
        for seed_url in seed_urls:
            normalized_seed = self._normalize_url("", seed_url) # Base URL not needed for initial seeds
            if normalized_seed and self.visited_set.add(normalized_seed):
                print(f"  Adding to frontier: {normalized_seed} (Depth: 0)")
                self.frontier_queue.put((normalized_seed, 0, normalized_seed))
                added_any = True
            elif normalized_seed:
                print(f"  Skipping already visited or invalid seed: {normalized_seed}")
            else:
                print(f"  Skipping invalid seed format: {seed_url}")
        
        # If new work is added, ensure the global event reflects that workers are 'active'
        if added_any and self.global_crawler_event and not self.global_crawler_event.is_set():
            self.global_crawler_event.set()

    def stop_workers(self):
        """
        Signals all worker threads to stop gracefully and waits for them to finish.
        This effectively stops the crawler.
        """
        if not self._is_workers_running:
            return

        print("Signaling crawler workers to stop gracefully...")
        # Put a poison pill for each worker to make them exit their blocking `get()`
        for _ in self._workers:
            self.frontier_queue.put(self._POISON_PILL)
        
        # Wait for all currently pending tasks (including poison pills) to be processed.
        # This will block until all `get()` and `task_done()` pairs have completed.
        self.frontier_queue.join() 
        
        if self.global_crawler_event:
            self.global_crawler_event.clear() # Clear the global event if crawler is stopping

        self._is_workers_running = False
        print("Crawler workers stopped.")


# --- Example Usage and Server Setup ---
if __name__ == "__main__":
    # 1. Initialize the thread-safe data structures
    visited_urls_set = ThreadSafeVisitedSet()
    inverted_index_map = ThreadSafeIndexMap()
    frontier_queue_instance = queue.Queue() # Using native queue.Queue for frontier (is thread-safe)
    crawler_running_event = threading.Event() # To signal crawler status to the dashboard

    # 2. Crawler Configuration
    MAX_CRAWL_DEPTH = 2  # Max depth to crawl (0 for seed only, 1 for seed + its links, etc.)
    NUM_CRAWLER_WORKERS = 3
    CRAWL_DELAY = 0.5 # Seconds between requests per worker (backpressure)

    crawler = Crawler(visited_urls_set, inverted_index_map,
                      frontier_queue_instance, MAX_CRAWL_DEPTH, CRAWL_DELAY,
                      global_crawler_event=crawler_running_event)

    # 3. Start the persistent Crawler workers in a separate thread
    # These workers will run in the background, blocking on the queue until tasks appear.
    crawler.start_workers(NUM_CRAWLER_WORKERS)
    print("Crawler system initialized and workers are ready.")

    # 4. Set up and run the Localhost API Server
    HOST = '127.0.0.1' # Adheres to (5.4) constraint: localhost only.
    PORT = 8000

    print(f"\n--- Starting VibeCrawler Localhost API Server ---")
    print(f"Server will be accessible at http://{HOST}:{PORT}")
    print(f"Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"Search API Example: http://{HOST}:{PORT}/search?q=python") 
    print("Type 'help' for commands, 'exit' to stop.")

    # Instantiate the custom server with references to the shared data structures.
    server = VibeCrawlerHTTPServer((HOST, PORT), VibeCrawlerRequestHandler,
                                   visited_urls_set, inverted_index_map,
                                   frontier_queue_instance, crawler_running_event)

    # Run the server in a separate thread to keep the main script responsive
    # and allow for a clean shutdown. Daemon thread ensures it doesn't prevent exit.
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    def print_status():
        print(f"\n--- Live Metrics ---")
        print(f"Visited URLs: {visited_urls_set.size()}")
        print(f"Indexed Keywords: {inverted_index_map.size()}")
        print(f"Indexed Entries: {inverted_index_map.total_entries()}")
        print(f"Frontier Queue Depth: {frontier_queue_instance.qsize()}")
        print(f"Crawler Status: {'Running' if crawler_running_event.is_set() else 'Stopped (Workers idle)'}")
        sys.stdout.flush()

    def print_help():
        print("\n--- CLI Commands ---")
        print("  crawl <url>           : Start crawling from the specified URL.")
        print("  search <query>        : Search the indexed content for keywords.")
        print("  status                : Display current crawler and index metrics.")
        print("  help                  : Show this help message.")
        print("  exit / quit           : Shut down the server and crawler gracefully.")
        sys.stdout.flush()

    print_help() # Show commands at startup

    try:
        # 5. Main CLI input loop
        while True:
            try:
                command_line = input("\nVibeCrawler> ").strip()
                if not command_line:
                    continue

                parts = command_line.split(' ', 1)
                command = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ''

                if command == 'crawl':
                    if not args:
                        print("Usage: crawl <url>")
                        sys.stdout.flush()
                        continue
                    # Add new crawl task asynchronously
                    print(f"Initiating crawl from: {args}")
                    sys.stdout.flush()
                    crawler.add_seeds([args]) # Add to the queue, workers will pick it up
                elif command == 'search':
                    if not args:
                        print("Usage: search <query>")
                        sys.stdout.flush()
                        continue
                    print(f"Searching for: '{args}'")
                    sys.stdout.flush()
                    results = inverted_index_map.search(args)
                    if results:
                        # Results are already sorted by frequency in the _handle_search method for API,
                        # but we can re-sort here for CLI consistency.
                        sorted_results = sorted(results, key=lambda x: x[3], reverse=True)
                        print(f"Found {len(sorted_results)} results:")
                        for i, (url, origin, depth, freq) in enumerate(sorted_results):
                            print(f"  {i+1}. URL: {url}")
                            print(f"     Origin: {origin}, Depth: {depth}, Frequency: {freq}")
                    else:
                        print("No results found.")
                    sys.stdout.flush()
                elif command == 'status':
                    print_status()
                elif command == 'help':
                    print_help()
                elif command in ['exit', 'quit']:
                    print("Exiting VibeCrawler. Shutting down...")
                    sys.stdout.flush()
                    break
                else:
                    print(f"Unknown command: '{command}'. Type 'help' for available commands.")
                    sys.stdout.flush()
            except EOFError: # Handles Ctrl+D
                print("\nEOF received. Exiting VibeCrawler.")
                sys.stdout.flush()
                break
            except Exception as e:
                print(f"An unexpected error occurred in CLI: {e}")
                sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n--- KeyboardInterrupt: Shutting down VibeCrawler Server and Crawler ---")
        sys.stdout.flush()
    finally:
        # Perform graceful shutdown of both crawler and server
        crawler.stop_workers() # Ensure crawler threads are gracefully shut down
        server.shutdown() # Shuts down the server, stopping the serve_forever loop.
        server.server_close() # Closes the server socket.
        print("Server and Crawler gracefully stopped.")
        sys.stdout.flush()
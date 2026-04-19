import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process

# 1. Securely load environment variables from the .env file
load_dotenv()

# The model specified for testing (handling version deprecations natively)
MODEL = 'gemini/gemini-2.5-flash'

# Load the PRD to act as the single source of truth
with open('product_prd.md', 'r') as f:
    prd_content = f.read()

current_code = ""
if os.path.exists('vibe_crawler.py'):
    with open('vibe_crawler.py', 'r') as f:
        current_code = f.read()

current_struct = ""
if os.path.exists('structures.py'):
    with open('structures.py', 'r') as f:
        current_struct = f.read()

# 2. Define the Agents based on PRD Section 5.3
system_architect = Agent(
    role='System Architect',
    goal='Refine technical specs and ensure the modularity of the Indexer and Searcher components.',
    backstory='You are a high-level software architect who designs concurrent systems and enforces strict zero-dependency protocols.',
    verbose=True,
    allow_delegation=False,
    llm=MODEL
)

backend_engineer = Agent(
    role='Backend Engineer',
    goal='Implement the core logic: recursive crawling, backpressure, and thread-safe data structures bound to localhost.',
    backstory='You write highly optimized, native-only Python code. You do not use external libraries for heavy lifting.',
    verbose=True,
    allow_delegation=False,
    llm=MODEL
)

qa_auditor = Agent(
    role='QA / Security Auditor',
    goal='Review code for race conditions and ensure the "Zero-Dependency" native constraint is met.',
    backstory='You are a meticulous auditor. You hunt for potential memory leaks, race conditions, and accidental use of external frameworks.',
    verbose=True,
    allow_delegation=False,
    llm=MODEL
)

devops_specialist = Agent(
    role='DevOps Specialist',
    goal='Focus on the "Human-in-the-Loop" verification protocols and system integration testing.',
    backstory='You bridge the gap between AI generation and manual developer approval, verifying environment conditions.',
    verbose=True,
    allow_delegation=False,
    llm=MODEL
)

# 3. Define the Tasks representing the Interaction Protocol

'''task_define_structures = Task(
    description=(
        f'Using the following PRD as your ONLY source of truth:\n\n{prd_content}\n\n'
        'Generate the foundational thread-safe data structures needed for the crawler and searcher. '
        'Provide a ThreadSafeVisitedSet and ThreadSafeIndexMap class, and the structural design for a localhost API. '
        'Do not use any third-party libraries.'
    ),
    expected_output='A clean Python file containing the core thread-safe data structures and API outline.',
    agent=system_architect,
    output_file='structures.py'
)
'''
task_write_logic = Task(
    description=(
        'Using the structures defined in structures.py, implement the recursive crawler, the '
        'search algorithm, AND the localhost API server (using native http.server). '
        'Ensure the server is accessible entirely via localhost (127.0.0.1) to expose real-time metrics. '
        'Focus on backpressure and handling depth limits using standard libraries like urllib and html.parser.'
    ),
    expected_output='A Python file with the complete crawler, searcher, and localhost server logic implemented.',
    agent=backend_engineer,
    output_file='vibe_crawler.py'
)


task_refine_logic = Task(
    description=(
        f"Using the current code as a base:\n\n{current_code}\n\n"
        "Modify the system to match these interactive requirements:\n"
        "1. PERSISTENCE: The localhost API server must run in a background thread and NEVER terminate "
        "even after a crawl finishes.\n"
        "2. CLI COMMANDS: Implement a 'while True' input loop in the main thread. The user should be able to type "
        "commands like 'crawl <url>', 'search <query>', or 'status'.\n"
        "3. RELEVANCY: Ensure the 'search' command and the API endpoint return TF-based frequency scores.\n"
        "4. ASYNC CRAWLING: When a user types 'crawl', it should start the worker pool without freezing the CLI."
    ),
    expected_output="An interactive vibe_crawler.py with a persistent CLI shell and background API.",
    agent=backend_engineer,
    output_file='vibe_crawler.py'
)

task_fix_shutdown = Task(
    description=(
        "The program hangs during shutdown. Refine vibe_crawler.py and structures.py to:\n"
        "1. Ensure ALL threads (Crawler workers and API Server) are set as 'daemon=True'.\n"
        "2. Implement a clean shutdown sequence where 'server.shutdown()' is called followed by "
        "explicitly clearing the 'frontier_queue' so workers can exit their loops.\n"
        "3. Use a 'threading.Event' to signal all workers to stop immediately upon 'exit' command."
    ),
    expected_output="A version of the system that exits instantly when 'exit' is typed.",
    agent=backend_engineer,
    context=[task_write_logic],
    output_file='vibe_crawler.py'
)

task_qa_review = Task(
    description=(
        'Read the code in vibe_crawler.py and structures.py. Look specifically for race conditions '
        'in the inverted index or visited set. Verify that zero external dependencies were used, '
        'and ensure the API endpoints are strictly bound to localhost. '
        'Provide a detailed report of any violations or confirm that the code is safe.'
    ),
    expected_output='A markdown audit report detailing thread safety, dependency compliance, and localhost binding.',
    agent=qa_auditor,
    output_file='qa_audit_report.md'
)

task_human_review_staging = Task(
    description=(
        'Compile a summary report of the built files. Document the instructions needed '
        'for the Human-in-the-Loop operator to execute the localhost server, test the API with Postman, '
        'and approve the staging codebase.'
    ),
    expected_output='A markdown document outlining the verification steps for the developer.',
    agent=devops_specialist,
    output_file='human_verification_guide.md'
)

task_readme_documentation = Task(
    description=(
        'Based on the verified code and the QA report, generate a comprehensive readme.md '
        'that explains how the system works, the architecture flow, and how to run the crawler locally.'
    ),
    expected_output='A comprehensive readme.md file ready for project submission.',
    agent=system_architect,
    output_file='readme.md'
)

task_recommendation_documentation = Task(
    description=(
        'Based on the verified code and the QA report, generate a recommendation.md file '
        'containing exactly two paragraphs: a roadmap for moving this prototype into a '
        'high-scale production environment (e.g., using distributed systems or cloud infra).'
    ),
    expected_output='A recommendation.md file containing the production roadmap.',
    agent=system_architect,
    output_file='recommendation.md'
)

# 4. Build and Run the Crew
vibe_crew = Crew(
    agents=[system_architect, backend_engineer, qa_auditor, devops_specialist],
    tasks=[
        task_define_structures, 
        task_write_logic,
        task_refine_logic, 
        task_fix_shutdown,
        task_qa_review, 
        task_human_review_staging, 
        task_readme_documentation, 
        task_recommendation_documentation
    ],
    process=Process.sequential # Keeps strict order according to the PRD pipeline
)

if __name__ == '__main__':
    print("Starting VibeCrawler Multi-Agent Pipeline...")
    result = vibe_crew.kickoff()
    print("\n--- Pipeline Completed ---")
    print(result)
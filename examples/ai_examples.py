"""AI content understanding examples.

Demonstrates how to use the AI processor for:
- Text summarization
- Question answering
- Key points extraction
- Content classification
- Tag generation
- Sentiment analysis
- Document comparison
- Entity extraction
"""

from webscout_mcp.ai_processor import AIConfig, AIProcessor


def example_summarization():
    """Example: Summarize web page content."""
    print("=" * 60)
    print("Example: Text Summarization")
    print("=" * 60)

    # Use local Ollama (free, no API key needed)
    config = AIConfig(backend="ollama", model="qwen2.5:7b")
    ai = AIProcessor(config=config)

    # Check if AI is available
    if not ai.is_available():
        print("Ollama not available. Install with:")
        print("  curl -fsSL https://ollama.com/install.sh | sh")
        print("  ollama pull qwen2.5:7b")
        return

    # Sample content (in real use, this would be fetched from a web page)
    content = """
    Artificial intelligence (AI) is the intelligence of machines or software,
    as opposed to the intelligence of humans or animals. It is a field of study
    in computer science that develops and studies intelligent machines. Such machines
    may be called AIs.

    AI technology is widely used throughout industry, government, and science.
    Some high-profile applications are: advanced web search engines (e.g., Google Search),
    recommendation systems (used by YouTube, Amazon, and Netflix), understanding human speech
    (such as Siri and Alexa), self-driving cars (e.g., Waymo), generative and creative tools
    (ChatGPT and AI art), and superhuman play and analysis in strategy games (chess and Go).

    The various sub-fields of AI research are centered around particular goals and
    the use of particular tools. The traditional goals of AI research include reasoning,
    knowledge representation, planning, learning, natural language processing, perception,
    and support for robotics.
    """

    # Summarize
    result = ai.summarize(content, max_length=200)
    print(f"Summary:\n{result.content}\n")


def example_question_answering():
    """Example: Answer questions based on context."""
    print("=" * 60)
    print("Example: Question Answering")
    print("=" * 60)

    config = AIConfig(backend="ollama", model="qwen2.5:7b")
    ai = AIProcessor(config=config)

    if not ai.is_available():
        print("Ollama not available. Skipping example.")
        return

    context = """
    Python is a high-level, general-purpose programming language. Its design philosophy
    emphasizes code readability with the use of significant indentation. Python is
    dynamically typed and garbage-collected. It supports multiple programming paradigms,
    including structured (particularly procedural), object-oriented and functional programming.

    Python was created by Guido van Rossum and first released in 1991. Python 2.0 was
    released in 2000 and Python 3.0 in 2008. Python consistently ranks as one of the
    most popular programming languages.
    """

    # Ask questions
    questions = [
        "Who created Python?",
        "When was Python first released?",
        "What programming paradigms does Python support?",
    ]

    for question in questions:
        result = ai.answer_question(context, question)
        print(f"Q: {question}")
        print(f"A: {result.content}\n")


def example_key_points():
    """Example: Extract key points from text."""
    print("=" * 60)
    print("Example: Key Points Extraction")
    print("=" * 60)

    config = AIConfig(backend="ollama", model="qwen2.5:7b")
    ai = AIProcessor(config=config)

    if not ai.is_available():
        print("Ollama not available. Skipping example.")
        return

    content = """
    Web scraping is the process of using bots to extract content and data from a website.
    Unlike screen scraping, which only copies pixels displayed onscreen, web scraping extracts
    underlying HTML code and, with it, data stored in a database. The scraper can then replicate
    entire website content elsewhere.

    Best practices for web scraping include:
    1. Respect robots.txt and website terms of service
    2. Use proper user-agent strings
    3. Implement rate limiting to avoid overwhelming servers
    4. Use caching to avoid repeated requests
    5. Handle errors gracefully with retries
    6. Use headless browsers for JavaScript-rendered content
    7. Rotate IP addresses and user agents for large-scale scraping
    """

    result = ai.extract_key_points(content, num_points=5)
    print(f"Key Points:\n{result.content}\n")


def example_classification():
    """Example: Classify content into categories."""
    print("=" * 60)
    print("Example: Content Classification")
    print("=" * 60)

    config = AIConfig(backend="ollama", model="qwen2.5:7b")
    ai = AIProcessor(config=config)

    if not ai.is_available():
        print("Ollama not available. Skipping example.")
        return

    categories = ["technology", "sports", "politics", "entertainment", "science"]

    articles = [
        "Apple announced new iPhone models with improved camera systems.",
        "The championship game ended with a last-minute touchdown.",
        "New legislation was passed to improve healthcare access.",
    ]

    for article in articles:
        result = ai.classify(article, categories)
        print(f"Article: {article[:50]}...")
        print(f"Category: {result.content}\n")


def example_sentiment():
    """Example: Analyze sentiment of text."""
    print("=" * 60)
    print("Example: Sentiment Analysis")
    print("=" * 60)

    config = AIConfig(backend="ollama", model="qwen2.5:7b")
    ai = AIProcessor(config=config)

    if not ai.is_available():
        print("Ollama not available. Skipping example.")
        return

    texts = [
        "This product is amazing! I love it and would recommend it to everyone.",
        "Terrible experience. The product broke after one day and customer service was unhelpful.",
        "The package arrived on time. It's okay, nothing special.",
    ]

    for text in texts:
        result = ai.analyze_sentiment(text)
        print(f"Text: {text[:60]}...")
        print(f"Sentiment: {result.content}\n")


def example_using_openai():
    """Example: Using OpenAI API instead of local Ollama."""
    print("=" * 60)
    print("Example: Using OpenAI API")
    print("=" * 60)

    # Use OpenAI API (requires API key)
    config = AIConfig(
        backend="openai",
        model="gpt-4o",
        api_key="your-openai-api-key-here",
    )
    ai = AIProcessor(config=config)

    print("To use OpenAI API, set your API key in the config or environment variable:")
    print("  export WEBSCOUT_AI_BACKEND=openai")
    print("  export WEBSCOUT_AI_MODEL=gpt-4o")
    print("  export WEBSCOUT_AI_API_KEY=your-key")
    print()


def run_all_examples():
    """Run all AI examples."""
    print("\n" + "=" * 60)
    print("  AI Content Understanding Examples")
    print("=" * 60 + "\n")

    example_summarization()
    example_question_answering()
    example_key_points()
    example_classification()
    example_sentiment()
    example_using_openai()

    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_examples()

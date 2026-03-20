#!/usr/bin/env python3
"""
Tests for Parthenon Brain v2 ingestion pipeline.

Run with:
    python -m pytest scripts/test_ingest.py -v
    python scripts/test_ingest.py  (standalone)
"""

import hashlib
import json
import tempfile
import textwrap
from pathlib import Path
from unittest import TestCase, main

from ingest import (
    chunk_by_headers,
    chunk_code_by_structure,
    chunk_id_from_content,
    chunk_python_ast,
    classify_file,
    detect_language,
    discover_files,
    estimate_tokens,
    should_skip,
    strip_frontmatter,
    strip_mdx_components,
)


class TestStripFrontmatter(TestCase):
    def test_basic_frontmatter(self):
        text = "---\ntitle: My Doc\ndate: 2026-01-15\n---\n\n# Hello\nContent here."
        meta, body = strip_frontmatter(text)
        self.assertEqual(meta['title'], 'My Doc')
        self.assertEqual(meta['date'], '2026-01-15')
        self.assertIn('# Hello', body)

    def test_no_frontmatter(self):
        text = "# Just a heading\nSome content."
        meta, body = strip_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_quoted_values(self):
        text = '---\ntitle: "Quoted Title"\nslug: \'my-slug\'\n---\nBody'
        meta, body = strip_frontmatter(text)
        self.assertEqual(meta['title'], 'Quoted Title')
        self.assertEqual(meta['slug'], 'my-slug')

    def test_empty_values_skipped(self):
        text = "---\ntitle: \nempty:\n---\nBody"
        meta, _ = strip_frontmatter(text)
        self.assertNotIn('title', meta)
        self.assertNotIn('empty', meta)


class TestStripMDX(TestCase):
    def test_removes_imports(self):
        text = "import MyComponent from './component'\n\n# Hello\nContent."
        result = strip_mdx_components(text)
        self.assertNotIn('import', result)
        self.assertIn('# Hello', result)

    def test_removes_jsx_self_closing(self):
        text = 'Some text <Alert type="info" /> more text'
        result = strip_mdx_components(text)
        self.assertIn('Some text', result)
        self.assertIn('more text', result)
        self.assertNotIn('Alert', result)

    def test_removes_jsx_tags_keeps_content(self):
        text = '<Callout>Important note here</Callout>'
        result = strip_mdx_components(text)
        self.assertIn('Important note here', result)

    def test_preserves_html_tags(self):
        text = '<div>this stays</div>'
        result = strip_mdx_components(text)
        self.assertIn('<div>', result)


class TestChunkByHeaders(TestCase):
    def test_single_section(self):
        text = "# Title\n\nSome paragraph content that is long enough to be a chunk." * 3
        chunks = chunk_by_headers(text)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(chunks[0]['section'], 'Title')

    def test_header_hierarchy(self):
        text = textwrap.dedent("""\
            # Top Level

            Some intro content that needs to be long enough.
            """ + "x " * 200 + """

            ## Second Level

            More content under second level.
            """ + "y " * 200 + """

            ### Third Level

            Deep content here.
            """ + "z " * 200)
        chunks = chunk_by_headers(text)
        self.assertGreaterEqual(len(chunks), 2)
        # The deeper chunks should have hierarchy
        sections = [c['section'] for c in chunks]
        has_nested = any('>' in s for s in sections)
        self.assertTrue(has_nested, f"Expected nested sections, got: {sections}")

    def test_empty_text(self):
        chunks = chunk_by_headers("")
        self.assertEqual(chunks, [])

    def test_short_fragments_skipped(self):
        chunks = chunk_by_headers("# Title\nHi")
        self.assertEqual(chunks, [])

    def test_force_split_on_large_chunk(self):
        # Create multiline content larger than max_tokens
        # Chunker splits at line boundaries, so we need many lines
        lines = ["# Big Section", ""] + [f"Line {i} with enough words to count." for i in range(200)]
        text = "\n".join(lines)
        chunks = chunk_by_headers(text, max_tokens=50)
        self.assertGreater(len(chunks), 1)


class TestChunkPythonAST(TestCase):
    def test_extracts_functions(self):
        code = textwrap.dedent("""\
            def hello(name: str) -> str:
                \"\"\"Greet someone.\"\"\"
                return f"Hello, {name}"

            def goodbye(name: str) -> str:
                \"\"\"Say bye.\"\"\"
                return f"Bye, {name}"
        """)
        chunks = chunk_python_ast(code, "test.py")
        symbols = [c['symbol'] for c in chunks]
        self.assertIn('hello', symbols)
        self.assertIn('goodbye', symbols)

    def test_extracts_classes(self):
        code = textwrap.dedent("""\
            class MyService:
                \"\"\"A service class.\"\"\"

                def __init__(self):
                    self.data = []

                def process(self, item):
                    self.data.append(item)
        """)
        chunks = chunk_python_ast(code, "test.py")
        kinds = {c['symbol']: c['kind'] for c in chunks}
        self.assertIn('MyService', kinds)
        self.assertEqual(kinds['MyService'], 'class')

    def test_handles_syntax_error(self):
        code = "def broken(\n    # missing closing paren"
        chunks = chunk_python_ast(code, "test.py")
        # Should fall back to structural chunking, not raise
        self.assertIsInstance(chunks, list)

    def test_module_docstring(self):
        code = '"""Module level docstring."""\n\ndef foo():\n    pass'
        chunks = chunk_python_ast(code, "test.py")
        has_module = any(c.get('kind') == 'module' for c in chunks)
        self.assertTrue(has_module)

    def test_async_functions(self):
        code = textwrap.dedent("""\
            async def fetch_data(url: str):
                \"\"\"Fetch data from URL.\"\"\"
                return await client.get(url)
        """)
        chunks = chunk_python_ast(code, "test.py")
        symbols = [c['symbol'] for c in chunks]
        self.assertIn('fetch_data', symbols)


class TestChunkCodeByStructure(TestCase):
    def test_typescript_functions(self):
        code = textwrap.dedent("""\
            export function calculateTotal(items: Item[]): number {
                return items.reduce((sum, item) => sum + item.price, 0);
            }

            export async function fetchData(url: string): Promise<Data> {
                const response = await fetch(url);
                return response.json();
            }
        """)
        chunks = chunk_code_by_structure(code, "utils.ts", lang="typescript")
        self.assertGreaterEqual(len(chunks), 1)

    def test_sql_statements(self):
        code = textwrap.dedent("""\
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL
            );

            CREATE INDEX idx_users_name ON users(name);

            INSERT INTO users (name) VALUES ('test');
        """)
        chunks = chunk_code_by_structure(code, "schema.sql", lang="sql")
        self.assertGreaterEqual(len(chunks), 1)

    def test_php_classes(self):
        code = textwrap.dedent("""\
            <?php

            class UserController extends Controller
            {
                public function index()
                {
                    return User::all();
                }

                public function store(Request $request)
                {
                    return User::create($request->all());
                }
            }
        """)
        chunks = chunk_code_by_structure(code, "UserController.php", lang="php")
        self.assertGreaterEqual(len(chunks), 1)


class TestChunkIdFromContent(TestCase):
    def test_deterministic(self):
        id1 = chunk_id_from_content("file.md", "some content here")
        id2 = chunk_id_from_content("file.md", "some content here")
        self.assertEqual(id1, id2)

    def test_different_content_different_id(self):
        id1 = chunk_id_from_content("file.md", "content A")
        id2 = chunk_id_from_content("file.md", "content B")
        self.assertNotEqual(id1, id2)

    def test_different_file_different_id(self):
        id1 = chunk_id_from_content("a.md", "same content")
        id2 = chunk_id_from_content("b.md", "same content")
        self.assertNotEqual(id1, id2)

    def test_length(self):
        cid = chunk_id_from_content("file.md", "content")
        self.assertEqual(len(cid), 32)


class TestClassifyFile(TestCase):
    def test_docs_directory(self):
        root = Path("/project")
        fp = Path("/project/docs/architecture/overview.md")
        result = classify_file(fp, root)
        self.assertEqual(result['doc_type'], 'architecture')

    def test_module_detection(self):
        root = Path("/project")
        fp = Path("/project/ai/app/routers/abby.py")
        result = classify_file(fp, root)
        self.assertEqual(result['module'], 'ai')

    def test_unknown_defaults(self):
        root = Path("/project")
        fp = Path("/project/random/file.txt")
        result = classify_file(fp, root)
        self.assertEqual(result['doc_type'], 'general')
        self.assertEqual(result['module'], 'unknown')


class TestDetectLanguage(TestCase):
    def test_python(self):
        self.assertEqual(detect_language(Path("app.py")), "python")

    def test_typescript(self):
        self.assertEqual(detect_language(Path("app.ts")), "typescript")
        self.assertEqual(detect_language(Path("App.tsx")), "typescript")

    def test_sql(self):
        self.assertEqual(detect_language(Path("schema.sql")), "sql")

    def test_php(self):
        self.assertEqual(detect_language(Path("Controller.php")), "php")

    def test_unknown(self):
        self.assertEqual(detect_language(Path("file.rb")), "generic")


class TestShouldSkip(TestCase):
    def test_skips_node_modules(self):
        self.assertTrue(should_skip(Path("/project/node_modules/pkg/index.js")))

    def test_skips_git(self):
        self.assertTrue(should_skip(Path("/project/.git/config")))

    def test_skips_binary(self):
        self.assertTrue(should_skip(Path("/project/image.png")))
        self.assertTrue(should_skip(Path("/project/archive.zip")))

    def test_allows_normal_files(self):
        self.assertFalse(should_skip(Path("/project/docs/readme.md")))
        self.assertFalse(should_skip(Path("/project/src/app.py")))


class TestDiscoverFiles(TestCase):
    def test_discovers_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "docs").mkdir()
            (root / "docs" / "readme.md").write_text("# Hello")
            (root / "docs" / "guide.txt").write_text("Guide content")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "pkg.md").write_text("Skip me")

            files = discover_files(root, ["**/*.md", "**/*.txt"])
            names = [f.name for f in files]
            self.assertIn("readme.md", names)
            self.assertIn("guide.txt", names)
            self.assertNotIn("pkg.md", names)


class TestEstimateTokens(TestCase):
    def test_basic(self):
        self.assertEqual(estimate_tokens("1234"), 1)
        self.assertEqual(estimate_tokens("12345678"), 2)
        self.assertEqual(estimate_tokens(""), 0)


if __name__ == '__main__':
    main()

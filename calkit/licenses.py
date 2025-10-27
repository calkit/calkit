"""Functionality for working with licenses.

Calkit projects will often include code, data, text, and other content
and artifacts that may each have their own license.
"""

LICENSE_TEMPLATE_DUAL = """
This project is licensed under a dual-license structure to appropriately cover
both the software code and the non-code content (data, text, figures, etc.).

Source code (MIT License)

All source code contained within this repository, including but not limited to
files with the extensions .js, .py, .html, .css, .ts, .jsx, .tsx, shell
scripts, build configurations, and their related files, is licensed under
the MIT License.

The MIT License (MIT)

Copyright (c) {year} {copyright_holder}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Content, data, and documentation (CC BY 4.0)

All non-code assets, including but not limited to prose, documentation, data,
figures, images, designs, and text written in Markdown or similar formats
(e.g., files in a docs/ directory, this LICENSE file itself, or .txt files
containing prose or data), are licensed under the Creative Commons Attribution
4.0 International Public License (CC BY 4.0).

To view a copy of this license, visit:

CC BY 4.0 Deed (summary):
https://creativecommons.org/licenses/by/4.0/

CC BY 4.0 Legal Code (full license):
https://creativecommons.org/licenses/by/4.0/legalcode

This license requires you to give appropriate credit, provide a link to the
license, and indicate if changes were made. You may do so in any reasonable
manner, but not in any way that suggests the licensor endorses you or your use.
""".strip()

// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// The expression engine's Web Worker (public/js/editor/evalWorker.ts), a script of its own.
// portal.py hands its URL to the page, whose engine.ts starts it.
import { serve } from "./editor/evalWorker.ts";

serve(self);

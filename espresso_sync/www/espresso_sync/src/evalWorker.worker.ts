// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// The expression engine's Web Worker (see public/js/editor/evalWorker.ts). engine.ts starts it.
import { serve } from "../../../public/js/editor/evalWorker.ts";

serve(self);

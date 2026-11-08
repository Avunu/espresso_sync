// Copyright (c) 2026, Avunu LLC and contributors
// For license information, please see license.txt

// The transform editor's JSONata worker (editor/evalWorker.ts, where it is typed and
// tested), a bundle of its own: portal.py hands its URL to the page in the boot.
import { serve } from "./editor/evalWorker.ts";

serve(self);

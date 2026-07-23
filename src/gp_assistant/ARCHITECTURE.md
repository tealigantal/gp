# GP Backend Architecture

The backend owns one typed recommendation lifecycle: a plan is selected by the Adaptive Decision Engine, a runtime observation records closed intraday evidence, and a publication projects those two immutable inputs. The application services are the only writers and the LLM is limited to publication-bound narration.

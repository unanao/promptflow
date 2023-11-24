# Promptflow examples

[![code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![license: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](../LICENSE)

## Get started

**Install dependencies**

- Bootstrap your python environment.
  - e.g: create a new [conda](https://conda.io/projects/conda/en/latest/user-guide/getting-started.html) environment. `conda create -n pf-examples python=3.9`.
  - install required packages in python environment : `pip install -r requirements.txt`
    - show installed sdk: `pip show promptflow`

**Quick start**

| path | status | description |
------|--------|-------------
| [quickstart.ipynb](tutorials/get-started/quickstart.ipynb) | [![samples_getstarted_quickstart](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstart.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstart.yml) | A quickstart tutorial to run a flow and evaluate it. |
| [quickstart-azure.ipynb](tutorials/get-started/quickstart-azure.ipynb) | [![samples_getstarted_quickstartazure](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstartazure.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstartazure.yml) | A quickstart tutorial to run a flow in Azure AI and evaluate it. |


## CLI examples

### Tutorials ([tutorials](tutorials))

| path | status | description |
------|--------|-------------
| [chat-with-pdf](tutorials/e2e-development/chat-with-pdf.md) | [![samples_tutorials_e2e_development_chat_with_pdf](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_e2e_development_chat_with_pdf.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_e2e_development_chat_with_pdf.yml) |  Retrieval Augmented Generation (or RAG) has become a prevalent pattern to build intelligent application with Large Language Models (or LLMs) since it can infuse external knowledge into the model, which is not trained with those up-to-date or proprietary information |
| [azure-app-service](tutorials/flow-deploy/azure-app-service/README.md) | [![samples_tutorials_flow_deploy_azure_app_service](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_azure_app_service.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_azure_app_service.yml) |  This example demos how to deploy a flow using Azure App Service |
| [distribute-flow-as-executable-app](tutorials/flow-deploy/distribute-flow-as-executable-app/README.md) | [![samples_tutorials_flow_deploy_distribute_flow_as_executable_app](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_distribute_flow_as_executable_app.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_distribute_flow_as_executable_app.yml) |  This example demos how to package flow as a executable app |
| [docker](tutorials/flow-deploy/docker/README.md) | [![samples_tutorials_flow_deploy_docker](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_docker.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_docker.yml) |  This example demos how to deploy flow as a docker app |
| [kubernetes](tutorials/flow-deploy/kubernetes/README.md) | [![samples_tutorials_flow_deploy_kubernetes](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_kubernetes.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_deploy_kubernetes.yml) |  This example demos how to deploy flow as a Kubernetes app |
| [promptflow-quality-improvement](tutorials/flow-fine-tuning-evaluation/promptflow-quality-improvement.md) | [![samples_tutorials_flow_fine_tuning_evaluation_promptflow_quality_improvement](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_fine_tuning_evaluation_promptflow_quality_improvement.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tutorials_flow_fine_tuning_evaluation_promptflow_quality_improvement.yml) |  This tutorial is designed to enhance your understanding of improving flow quality through prompt tuning and evaluation |


### Flows ([flows](flows))

#### [Standard flows](flows/standard/)

| path | status | description |
------|--------|-------------
| [autonomous-agent](flows/standard/autonomous-agent/README.md) | [![samples_flows_standard_autonomous_agent](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_autonomous_agent.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_autonomous_agent.yml) | This is a flow showcasing how to construct a AutoGPT agent with promptflow to autonomously figures out how to apply the given functions to solve the goal, which is film trivia that provides accurate and up-to-date information about movies, directors, actors, and more in this sample |
| [basic](flows/standard/basic/README.md) | [![samples_flows_standard_basic](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_basic.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_basic.yml) |  A basic standard flow using custom python tool that calls Azure OpenAI with connection info stored in environment variables |
| [basic-with-builtin-llm](flows/standard/basic-with-builtin-llm/README.md) | [![samples_flows_standard_basic_with_builtin_llm](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_basic_with_builtin_llm.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_basic_with_builtin_llm.yml) |  A basic standard flow that calls Azure OpenAI with builtin llm tool |
| [basic-with-connection](flows/standard/basic-with-connection/README.md) | [![samples_flows_standard_basic_with_connection](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_basic_with_connection.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_basic_with_connection.yml) |  A basic standard flow that using custom python tool calls Azure OpenAI with connection info stored in custom connection |
| [conditional-flow-for-if-else](flows/standard/conditional-flow-for-if-else/README.md) | [![samples_flows_standard_conditional_flow_for_if_else](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_conditional_flow_for_if_else.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_conditional_flow_for_if_else.yml) |  This example is a conditional flow for if-else scenario |
| [conditional-flow-for-switch](flows/standard/conditional-flow-for-switch/README.md) | [![samples_flows_standard_conditional_flow_for_switch](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_conditional_flow_for_switch.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_conditional_flow_for_switch.yml) |  This example is a conditional flow for switch scenario |
| [customer-intent-extraction](flows/standard/customer-intent-extraction/README.md) | [![samples_flows_standard_customer_intent_extraction](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_customer_intent_extraction.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_customer_intent_extraction.yml) |  This sample is using OpenAI chat model(ChatGPT/GPT4) to identify customer intent from customer's question |
| [flow-with-additional-includes](flows/standard/flow-with-additional-includes/README.md) | [![samples_flows_standard_flow_with_additional_includes](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_flow_with_additional_includes.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_flow_with_additional_includes.yml) |  User sometimes need to reference some common files or folders, this sample demos how to solve the problem using additional_includes |
| [flow-with-symlinks](flows/standard/flow-with-symlinks/README.md) | [![samples_flows_standard_flow_with_symlinks](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_flow_with_symlinks.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_flow_with_symlinks.yml) |  User sometimes need to reference some common files or folders, this sample demos how to solve the problem using symlinks |
| [gen-docstring](flows/standard/gen-docstring/README.md) | [![samples_flows_standard_gen_docstring](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_gen_docstring.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_gen_docstring.yml) |  This example can help you automatically generate Python code's docstring and return the modified code |
| [maths-to-code](flows/standard/maths-to-code/README.md) | [![samples_flows_standard_maths_to_code](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_maths_to_code.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_maths_to_code.yml) |  Math to Code is a project that utilizes the power of the chatGPT model to generate code that models math questions and then executes the generated code to obtain the final numerical answer |
| [named-entity-recognition](flows/standard/named-entity-recognition/README.md) | [![samples_flows_standard_named_entity_recognition](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_named_entity_recognition.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_named_entity_recognition.yml) |  A flow that perform named entity recognition task |
| [web-classification](flows/standard/web-classification/README.md) | [![samples_flows_standard_web_classification](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_web_classification.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_standard_web_classification.yml) |  This is a flow demonstrating multi-class classification with LLM |


#### [Evaluation flows](flows/evaluation/)

| path | status | description |
------|--------|-------------
| [eval-basic](flows/evaluation/eval-basic/README.md) | [![samples_flows_evaluation_eval_basic](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_basic.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_basic.yml) |  This example shows how to create a basic evaluation flow |
| [eval-chat-math](flows/evaluation/eval-chat-math/README.md) | [![samples_flows_evaluation_eval_chat_math](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_chat_math.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_chat_math.yml) |  This example shows how to evaluate the answer of math questions, which can compare the output results with the standard answers numerically |
| [eval-classification-accuracy](flows/evaluation/eval-classification-accuracy/README.md) | [![samples_flows_evaluation_eval_classification_accuracy](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_classification_accuracy.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_classification_accuracy.yml) |  This is a flow illustrating how to evaluate the performance of a classification system |
| [eval-entity-match-rate](flows/evaluation/eval-entity-match-rate/README.md) | [![samples_flows_evaluation_eval_entity_match_rate](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_entity_match_rate.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_entity_match_rate.yml) |  This is a flow evaluates: entity match rate |
| [eval-groundedness](flows/evaluation/eval-groundedness/README.md) | [![samples_flows_evaluation_eval_groundedness](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_groundedness.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_groundedness.yml) |  This is a flow leverage llm to eval groundedness: whether answer is stating facts that are all present in the given context |
| [eval-perceived-intelligence](flows/evaluation/eval-perceived-intelligence/README.md) | [![samples_flows_evaluation_eval_perceived_intelligence](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_perceived_intelligence.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_evaluation_eval_perceived_intelligence.yml) |  This is a flow leverage llm to eval perceived intelligence |


#### [Chat flows](flows/chat/)

| path | status | description |
------|--------|-------------
| [basic-chat](flows/chat/basic-chat/README.md) | [![samples_flows_chat_basic_chat](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_basic_chat.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_basic_chat.yml) |  This example shows how to create a basic chat flow |
| [chat-math-variant](flows/chat/chat-math-variant/README.md) | [![samples_flows_chat_chat_math_variant](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chat_math_variant.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chat_math_variant.yml) |  This is a prompt tuning case with 3 prompt variants for math question answering |
| [chat-with-pdf](flows/chat/chat-with-pdf/README.md) | [![samples_flows_chat_chat_with_pdf](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chat_with_pdf.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chat_with_pdf.yml) |  This is a simple flow that allow you to ask questions about the content of a PDF file and get answers |
| [chat-with-wikipedia](flows/chat/chat-with-wikipedia/README.md) | [![samples_flows_chat_chat_with_wikipedia](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chat_with_wikipedia.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chat_with_wikipedia.yml) |  This flow demonstrates how to create a chatbot that can remember previous interactions and use the conversation history to generate next message |


### Tool Use Cases ([Tool Use Cases](tools/use-cases))

| path | status | description |
------|--------|-------------
| [cascading-inputs-tool-showcase](tools/use-cases/cascading-inputs-tool-showcase/README.md) | [![samples_tools_use_cases_cascading_inputs_tool_showcase](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_cascading_inputs_tool_showcase.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_cascading_inputs_tool_showcase.yml) | This is a flow demonstrating the use of a tool with cascading inputs which frequently used in situations where the selection in one input field determines what subsequent inputs should be shown, and it helps in creating a more efficient, user-friendly, and error-free input process |
| [custom-strong-type-connection-package-tool-showcase](tools/use-cases/custom-strong-type-connection-package-tool-showcase/README.md) | [![samples_tools_use_cases_custom_strong_type_connection_package_tool_showcase](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_custom_strong_type_connection_package_tool_showcase.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_custom_strong_type_connection_package_tool_showcase.yml) |  This is a flow demonstrating the use of a package tool with custom string type connection which provides a secure way to manage credentials for external APIs and data sources, and it offers an improved user-friendly and intellisense experience compared to custom connections |
| [custom-strong-type-connection-script-tool-showcase](tools/use-cases/custom-strong-type-connection-script-tool-showcase/README.md) | [![samples_tools_use_cases_custom_strong_type_connection_script_tool_showcase](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_custom_strong_type_connection_script_tool_showcase.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_custom_strong_type_connection_script_tool_showcase.yml) |  This is a flow demonstrating the use of a script tool with custom string type connection which provides a secure way to manage credentials for external APIs and data sources, and it offers an improved user-friendly and intellisense experience compared to custom connections |
| [custom_llm_tool_showcase](tools/use-cases/custom_llm_tool_showcase/README.md) | [![samples_tools_use_cases_custom_llm_tool_showcase](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_custom_llm_tool_showcase.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_custom_llm_tool_showcase.yml) |  This is a flow demonstrating how to use a `custom_llm` tool, which enables users to seamlessly connect to a large language model with prompt tuning experience using a `PromptTemplate` |
| [dynamic-list-input-tool-showcase](tools/use-cases/dynamic-list-input-tool-showcase/README.md) | [![samples_tools_use_cases_dynamic_list_input_tool_showcase](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_dynamic_list_input_tool_showcase.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_tools_use_cases_dynamic_list_input_tool_showcase.yml) |  This is a flow demonstrating how to use a tool with a dynamic list input |


### Connections ([connections](connections))

| path | status | description |
------|--------|-------------
| [connections](connections/README.md) | [![samples_connections](https://github.com/microsoft/promptflow/actions/workflows/samples_connections.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_connections.yml) |  This folder contains example `YAML` files for creating `connection` using `pf` cli |



## SDK examples

| path | status | description |
------|--------|-------------
| [quickstart.ipynb](tutorials/get-started/quickstart.ipynb) | [![samples_getstarted_quickstart](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstart.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstart.yml) | A quickstart tutorial to run a flow and evaluate it. |
| [quickstart-azure.ipynb](tutorials/get-started/quickstart-azure.ipynb) | [![samples_getstarted_quickstartazure](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstartazure.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_quickstartazure.yml) | A quickstart tutorial to run a flow in Azure AI and evaluate it. |
| [pipeline.ipynb](tutorials/flow-in-pipeline/pipeline.ipynb) | [![samples_flowinpipeline_pipeline](https://github.com/microsoft/promptflow/actions/workflows/samples_flowinpipeline_pipeline.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flowinpipeline_pipeline.yml) | Create pipeline using components to run a distributed job with tensorflow |
| [flow-as-function.ipynb](tutorials/get-started/flow-as-function.ipynb) | [![samples_getstarted_flowasfunction](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_flowasfunction.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_getstarted_flowasfunction.yml) | This guide will walk you through the main scenarios of executing flow as a function. |
| [cloud-run-management.ipynb](tutorials/run-management/cloud-run-management.ipynb) | [![samples_runmanagement_cloudrunmanagement](https://github.com/microsoft/promptflow/actions/workflows/samples_runmanagement_cloudrunmanagement.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_runmanagement_cloudrunmanagement.yml) | Flow run management in Azure AI |
| [run-management.ipynb](tutorials/run-management/run-management.ipynb) | [![samples_runmanagement_runmanagement](https://github.com/microsoft/promptflow/actions/workflows/samples_runmanagement_runmanagement.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_runmanagement_runmanagement.yml) | Flow run management |
| [connection.ipynb](connections/connection.ipynb) | [![samples_connections_connection](https://github.com/microsoft/promptflow/actions/workflows/samples_connections_connection.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_connections_connection.yml) | Manage various types of connections using sdk |
| [chat-with-pdf-azure.ipynb](flows/chat/chat-with-pdf/chat-with-pdf-azure.ipynb) | [![samples_flows_chat_chatwithpdf_chatwithpdfazure](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chatwithpdf_chatwithpdfazure.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chatwithpdf_chatwithpdfazure.yml) | A tutorial of chat-with-pdf flow that executes in Azure AI |
| [chat-with-pdf.ipynb](flows/chat/chat-with-pdf/chat-with-pdf.ipynb) | [![samples_flows_chat_chatwithpdf_chatwithpdf](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chatwithpdf_chatwithpdf.yml/badge.svg?branch=main)](https://github.com/microsoft/promptflow/actions/workflows/samples_flows_chat_chatwithpdf_chatwithpdf.yml) | A tutorial of chat-with-pdf flow that allows user ask questions about the content of a PDF file and get answers |



## Contributing

We welcome contributions and suggestions! Please see the [contributing guidelines](../CONTRIBUTING.md) for details.

## Code of Conduct

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). Please see the [code of conduct](../CODE_OF_CONDUCT.md) for details.

## Reference

* [Promptflow documentation](https://microsoft.github.io/promptflow/)

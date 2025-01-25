import os

class PathConfig:
    # 基础路径配置
    BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    
    # pdf2jpg.py使用的路径配置
    PDF2JPG_INPUT = f"{BASE_DIR}/input_pdf"  # 输入PDF文件路径
    PDF2JPG_OUTPUT = f"{BASE_DIR}/mark/input_image"  # 转换后的图片输出路径

    # image_marker（原1_picMark.py）相关路径配置
    PICMARK_INPUT_DIR = f"{BASE_DIR}/mark/input_image"      # 原1_picMark/inputPic
    PICMARK_OUTPUT_DIR = f"{BASE_DIR}/mark/image_metadata"  # 原1_picMark/picJSON

    # image_preprocessor（原2_picProcess.py）相关路径配置
    IMAGE_PREPROCESSOR_INPUT = f"{BASE_DIR}/mark/input_image"  # 原1_picMark/inputPic
    IMAGE_PREPROCESSOR_JSON = f"{BASE_DIR}/mark/image_metadata"  # 原1_picMark/picJSON
    IMAGE_PREPROCESSOR_OUTPUT = f"{BASE_DIR}/processed_images"  # 原2_outputPic
    IMAGE_PREPROCESSOR_CUT = f"{BASE_DIR}/image_cropper"  # 原6_1_cutPic

    # ocr_azure.py (原 3_1_AzureOCR.py) 相关路径配置
    OCR_AZURE_INPUT_1 = f"{BASE_DIR}/processed_images"  # 原 2_outputPic
    OCR_AZURE_OUTPUT_1 = f"{BASE_DIR}/ocr_results"  # 原 3_1_OCRServiceBack

    # ocr_aliyun.py (原 3_2_AliyunOCR.py) 相关路径配置
    ALIYUN_OCR_INPUT = f"{BASE_DIR}/processed_images"  # 原 2_outputPic
    ALIYUN_OCR_OUTPUT = f"{BASE_DIR}/ocr_results"  # 原 3_1_OCRServiceBack

    # ocr_processor.py (原 3_3_OCRProcess.py) 相关路径配置
    OCRPROCESS_INPUT_1 = f"{BASE_DIR}/processed_images"  # 原2_outputPic
    OCRPROCESS_INPUT_2 = f"{BASE_DIR}/ocr_results"  # 原3_1_OCRServiceBack
    OCRPROCESS_OUTPUT_1 = f"{BASE_DIR}/ocr_extracted_text"  # 原3_OCRInfo

    # text_matcher（原4_matchText）相关路径配置
    TEXT_MATCHER_INPUT = f"{BASE_DIR}/ocr_extracted_text"  # 原3_OCRInfo
    TEXT_MATCHER_OUTPUT = f"{BASE_DIR}/raw_content"  # 原4_initialContentInfo

    # content_preprocessor.py（原 5_1_json_preprocess.py）相关路径配置
    CONTENT_PREPROCESSOR_INPUT = f"{BASE_DIR}/raw_content"  # 原4_initialContentInfo

    # llm_handler.py (原 5_2_model_process.py) 相关路径配置
    LLM_HANDLER_INPUT = f"{BASE_DIR}/raw_content"          # 原 4_initialContentInfo
    LLM_HANDLER_OUTPUT = f"{BASE_DIR}/llm_processed_content"  # 原 4_1_LLMProcessed

    # result_merger.py（原 5_3_result_merge.py）相关路径配置
    RESULT_MERGER_INPUT_RAW = f"{BASE_DIR}/raw_content"  # 原 4_initialContentInfo
    RESULT_MERGER_INPUT_LLM = f"{BASE_DIR}/llm_processed_content"  # 原 4_1_LLMProcessed 
    RESULT_MERGER_OUTPUT = f"{BASE_DIR}/merged_content"  # 原 5_processedContentInfo
    RESULT_MERGER_LOGS = f"{BASE_DIR}/logs"  # 日志目录

    # result_merger_trad.py（原 5_3_result_merge.py）相关路径配置
    RESULT_MERGER_TRAD_INPUT_RAW = f"{BASE_DIR}/raw_content"  # 原 4_initialContentInfo
    RESULT_MERGER_TRAD_INPUT_LLM = f"{BASE_DIR}/llm_processed_content"  # 原 4_1_LLMProcessed 
    RESULT_MERGER_TRAD_OUTPUT = f"{BASE_DIR}/level_adjusted_content"  # 原 5_processedContentInfo
    RESULT_MERGER_TRAD_LOGS = f"{BASE_DIR}/logs"  # 日志目录

    # llm_level_adjuster相关路径配置
    LEVEL_ADJUSTER_INPUT = f"{BASE_DIR}/merged_content"  # 输入目录
    LEVEL_ADJUSTER_OUTPUT = f"{BASE_DIR}/level_adjusted_content"  # 输出目录
    LEVEL_ADJUSTER_CACHE = f"{BASE_DIR}/level_adjuster_cache"  # 缓存目录

    # content_validator.py（原 6_confirmContent.py）相关路径配置
    CONTENT_VALIDATOR_INPUT = f"{BASE_DIR}/level_adjusted_content"  # 原 5_processedContentInfo
    CONTENT_VALIDATOR_OUTPUT = f"{BASE_DIR}/validated_content"  # 原 6_confirmedContentInfo
    CONTENT_VALIDATOR_IMAGES = f"{BASE_DIR}/image_cropper"  # 原 6_1_cutPic

    # pdf_generator.py（原 7_processPDF.py）相关路径配置
    PDF_GENERATOR_INPUT_1 = f"{BASE_DIR}/validated_content"  # 原 6_confirmedContentInfo
    PDF_GENERATOR_INPUT_2 = f"{BASE_DIR}/input_pdf"  # 原 0_originPDF
    PDF_GENERATOR_OUTPUT_1 = f"{BASE_DIR}/output_pdf"  # 原 7_processedPDF


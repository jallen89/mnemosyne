
# Nodes

| Frame ||
| ---------------|-|
| id  | frameId-loaderId |
| frameId | 
| loaderId | 
| securityOrigin | 
| url | 
| execContext |
| name | 
| type | iframe/page |
| requests | 0 |
| responses | 0 |
| scriptesParsed | 0 |


| Parser ||
|--------------|-|
| id | frameId-loaderId |


| Resource||
| --------------|-|
| type | img/xhr/script/... |
| path | images.jpost.com/image/upload/f_auto,fl_lossy/t_CategoryFiveArticlesBFaceDetect/448581 |
| id | same with path |


|Script ||
|-------|--------------------------|
| id  | frameId-loaderId-scriptId |
| scriptId |
| frameId |
| loaderId |
| execContext | 
| hash | 
| url | 


| Remote Host ||
|--------------|-|
| id | ip |
| domain | 
| server | 
| type | 
| rip | remote ip|


# Edges

Each edge has an ID named label-id-startNode-endNode

| Attached ||
--------------|-|
| type | attached |
| scriptId | callframe scriptId|
| url | callframe url|


| Compiled ||
--------------|-|
| type | compiled |
| exeContext|


| Created ||
--------------|-|
| type | created |


| Frame Parser ||
--------------|-|
| type | frame parser |


| Location ||
--------------|-|
| transitionType | ? |


| Navigated ||
--------------|-|
| type |


| Version ||
--------------|-|
| type |


| Opened ||
| -- | -- |
| | |

| ParentChild ||
| -- | -- |
| | |


| Request ||
--------------|-|
| type |
| wallTime |
| hasUserGesture |
| requestId |
| timestamp |
| method |


| Response ||
--------------|-|
| type |
| status |
| rip* | |


| Source ||
--------------|-|
| type |

| Download ||
| -- | -- |
| domain | |
| path | |

## Record

| RedirectRecord | |
| -- | -- |
| id |
| scriptId |
| oldLoaderId |
| newLoaderId |
| frameId |
import cv2
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
while True:
    ret, frame = cap.read()
    if not ret:
        print("读取失败")
        break
    cv2.imshow("USB", frame)
    if cv2.waitKey(1) == ord('q'):
        break
cap.release()
cv2.destroyAllWindows()